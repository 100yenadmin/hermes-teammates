"""Deterministic r3 graders; submitted tests run on pristine isolated variants."""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

from bench.drivers.hermes_cell import sandbox_profile
from .texts import ARMS, ROLES
from .venv import ensure_bench_python

SCRATCH = Path('/Users/m1/Codex/bench-slice3-grading')
_CITATION = re.compile(r'^docs/([^\]:\n]+):([0-9]+)\]$')
_FINDING = re.compile(r'^- ([^\s:|]+):([0-9]+) \| (P[123]) \| ([^|]+) \| (.+)$')
_VERDICT = re.compile(r'^VERDICT: (approve|request-changes)$')
_ANSWER = re.compile(r'^ANSWER: \S.*$')
_FAILURES = re.compile(r'\b[0-9]+ failed\b')


def _safe_file(root, relative):
    """Existing regular files only, with no symlink or traversal escapes."""
    path = PurePosixPath(relative)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        return None
    target = Path(root) / path
    if any(parent.is_symlink() for parent in (target, *target.parents)
           if parent != Path(root).parent):
        return None
    if not target.is_file() or not target.resolve().is_relative_to(Path(root).resolve()):
        return None
    return target


def _lines(text):
    return [line for line in text.splitlines() if line.strip()]


def _line_number(digits):
    # No real fixture has a billion lines; avoid Python's huge-int conversion limit.
    return int(digits) if len(digits) <= 9 else 0


def _citations(text):
    # Split delimiters first: repeated unfinished citation prefixes stay linear.
    for candidate in text.split('[')[1:]:
        prefix, closing, _ = candidate.partition(']')
        if closing:
            match = _CITATION.fullmatch(prefix + ']')
            if match:
                yield 'docs/' + match[1], _line_number(match[2])


def _findings(text):
    rows = []
    for line in text.splitlines():
        if line.startswith('- '):
            match = _FINDING.fullmatch(line)
            rows.append(None if match is None else
                        {'file': match[1], 'line': _line_number(match[2]), 'priority': match[3],
                         'problem': match[4], 'fix': match[5]})
    return rows


def _paths(delta):
    return [path for kind in ('added', 'modified', 'deleted') for path in delta.get(kind, [])
            if '.git' not in PurePosixPath(path).parts
            and '__pycache__' not in PurePosixPath(path).parts and not path.endswith('.pyc')]


def _test_identity(oracle):
    slug = oracle['ticket'].lower().replace('-', '_')
    file = f'tests/test_{slug}.py'
    function = f'test_{slug}_regression'
    return file, function, f'{file}::{function}'


def _red_receipt(receipts, filename):
    for receipt in receipts:
        if receipt.get('tool') != 'terminal':
            continue
        command = receipt.get('args', {}).get('command', '')
        if not isinstance(command, str) or 'pytest' not in command or filename not in command:
            continue
        result = receipt.get('result_text', '')
        # Hermes terminal results are JSON envelopes. "error": null is metadata,
        # not a pytest collection error. Truncated head/tail envelopes may no longer
        # be valid JSON, but their escaped output line breaks still separate summaries.
        try:
            envelope = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            result = result.replace('\\n', '\n')
        else:
            if isinstance(envelope, dict) and isinstance(envelope.get('output'), str):
                if envelope.get('error'):
                    continue
                result = envelope['output']
        summaries = [line.lower() for line in result.splitlines() if _FAILURES.search(line.lower())]
        if any('error' not in summary for summary in summaries) and receipt.get('exit_code') in (None, 1):
            # A separate pytest ERROR summary must not be hidden by a failure detail line.
            if not any('error' in line.lower() for line in result.splitlines()
                       if line.startswith('=') or re.match(r'^\s*[0-9]+ .* in ', line)):
                return True
    return False


def check_rules(role, oracle_turn, text, delta, receipts, workspace: Path) -> list[bool]:
    lines, paths = _lines(text), _paths(delta)
    last = lines[-1] if lines else ''
    if role == 'scout':
        cites = list(_citations(text))
        valid = bool(cites)
        for file, line in cites:
            source = _safe_file(workspace, file)
            valid = valid and source is not None and 1 <= line <= len(source.read_text().splitlines())
        return [not paths, bool(valid), len(' '.join(lines[:-1]).split()) <= 80,
                bool(_ANSWER.fullmatch(last))]
    if role == 'reviewer':
        findings = _findings(text)
        return [not paths, all(f is not None for f in findings), len(findings) <= 5,
                bool(_VERDICT.fullmatch(last))]
    if role == 'tester':
        file, function, node = _test_identity(oracle_turn)
        submitted = _safe_file(workspace, file)
        content = submitted.read_text() if submitted else ''
        only_tests = all(PurePosixPath(p).parts[0] == 'tests' and '..' not in PurePosixPath(p).parts
                         for p in paths if PurePosixPath(p).parts)
        try:
            tree = ast.parse(content)
            has_function = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                               and n.name == function for n in tree.body)
        except SyntaxError:
            has_function = False
        return [only_tests, file in delta.get('added', []) and has_function,
                any(line == 'RED: ' + node for line in lines) and _red_receipt(receipts, file),
                bool(submitted) and not any(token in content for token in ('pytest.mark', 'skip(', 'xfail('))]
    raise ValueError(f'Unknown role: {role}')


def _normal(value):
    return ' '.join(str(value).strip().strip('`').casefold().split())


def _accepted_answers(oracle):
    values = oracle['accepted'] if 'accepted' in oracle else [oracle['answer']]
    return [_normal(value) for value in values if _normal(value)]


def _matches_path(submitted, expected):
    """Accept one diff prefix or a shortened path on a component boundary."""
    for prefix in ('a/', 'b/', './'):
        if submitted.startswith(prefix):
            submitted = submitted[len(prefix):]
            break
    return submitted == expected or expected.endswith('/' + submitted)


def _matches_bug(finding, bug):
    return (finding is not None and _matches_path(finding['file'], bug['file'])
            and abs(finding['line'] - bug['line']) <= 2
            and any(term in (finding['problem'] + ' ' + finding['fix']).casefold()
                    for term in bug['terms']))


def _sandbox(run, venv, python):
    """Reuse the proven sandbox; only the external bench venv is added."""
    venv = Path(venv).resolve()
    metadata = ' '.join(f'(literal {json.dumps(str(p))})' for p in venv.parents)
    return (sandbox_profile(run) + '(deny network*)\n'
            + f'(allow file-read* (subpath {json.dumps(str(venv))}))\n'
            + f'(allow file-read-metadata {metadata})\n')


def _run_node(work, node, python, venv):
    junit = work.parent / 'junit.xml'
    # Hermetic: no config, conftest or package above the work dir may shape the run or its node ids.
    ini = work / 'pytest.ini'
    if not ini.is_file():
        ini = work.parent / 'grader-pytest.ini'
        ini.write_text('[pytest]\n')
    command = [str(python), '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-c', str(ini), f'--rootdir={work}',
               f'--confcutdir={work}', f'--junitxml={junit}', node]
    if sys.platform == 'darwin':
        profile = work.parent / 'pytest.sb'
        profile.write_text(_sandbox(work.parent, venv, python))
        command = ['/usr/bin/sandbox-exec', '-f', str(profile), *command]
    env = {'PATH': str(venv / 'bin') + ':/usr/bin:/bin', 'HOME': str(work.parent),
           'TMPDIR': str(work.parent), 'PYTHONDONTWRITEBYTECODE': '1',
           'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'HERMES_DISABLE_LAZY_INSTALLS': '1',
           'LANG': 'en_US.UTF-8'}
    try:
        result = subprocess.run(command, cwd=work, env=env, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {'exit': None, 'state': 'timeout'}
    try:
        report = ET.parse(junit).getroot()
        cases = list(report.iter('testcase'))
        expected_function = node.split('::')[1]
        expected_class = node.split('::')[0].removesuffix('.py').replace('/', '.')
        if len(cases) != 1 or cases[0].get('name') != expected_function or cases[0].get('classname') != expected_class:
            state = 'invalid-node'
        elif list(report.iter('error')) or cases[0].find('skipped') is not None:
            state = 'error'
        elif cases[0].find('failure') is not None:
            failure = cases[0].find('failure')
            description = failure.get('message', '') + '\n' + (failure.text or '')
            assertion = any(token in description for token in
                            ('AssertionError', 'assert ', 'DID NOT RAISE', 'DID NOT WARN'))
            state = 'failure' if assertion else 'error'
        else:
            state = 'passed'
    except (OSError, ET.ParseError):
        state = 'missing-junit'
    return {'exit': result.returncode, 'state': state}


def _tester_success(oracle, workspace, pristine):
    file, _, node = _test_identity(oracle)
    submitted = _safe_file(workspace, file)
    if submitted is None:
        return {'success': False, 'fp': None, 'detail': 'submitted test absent or unsafe'}
    # Snapshot submitted bytes once; buggy and fixed trees get identical support.
    content = submitted.read_bytes()
    venv = ensure_bench_python()
    python = venv / 'bin/python'
    SCRATCH.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='grade-', dir=SCRATCH) as directory:
        root = Path(directory)
        outcomes = []
        for label in ('buggy', 'fixed'):
            work = root / label / 'work'
            shutil.copytree(pristine, work, ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
            (work / file).parent.mkdir(parents=True, exist_ok=True)
            (work / file).write_bytes(content)
            if label == 'fixed':
                for relative, fix in oracle['fix_files'].items():
                    target = _safe_file(work, relative)
                    if target is None or not relative.startswith('src/'):
                        raise ValueError('Invalid reference fix path')
                    target.write_text(fix)
            outcomes.append(_run_node(work, node, python, venv))
    success = outcomes == [{'exit': 1, 'state': 'failure'}, {'exit': 0, 'state': 'passed'}]
    return {'success': success, 'fp': None,
            'detail': f'buggy={outcomes[0]["state"]}/{outcomes[0]["exit"]}; fixed={outcomes[1]["state"]}/{outcomes[1]["exit"]}'}


def child_success(role, oracle_turn, text, workspace: Path, pristine: Path, receipts) -> dict:
    if role == 'scout':
        lines = _lines(text)
        answer = lines[-1].removeprefix('ANSWER: ') if lines and lines[-1].startswith('ANSWER: ') else None
        citation = oracle_turn['citation']
        valid_cite = any(file == citation['file'] and abs(line - citation['line']) <= 2
                         and _safe_file(workspace, file) is not None for file, line in _citations(text))
        success = answer is not None and _normal(answer) in _accepted_answers(oracle_turn) and valid_cite
        return {'success': bool(success), 'fp': None, 'detail': 'answer and planted citation' if success else 'answer or citation mismatch'}
    if role == 'reviewer':
        lines = _lines(text)
        verdict = _VERDICT.fullmatch(lines[-1]) if lines else None
        findings = _findings(text)
        supported = [finding for finding in findings if finding is not None]
        if oracle_turn['verdict'] == 'approve':
            fp = len(findings)
            high = sum(f['priority'] in ('P1', 'P2') for f in supported) + findings.count(None)
            success = verdict is not None and verdict[1] == 'approve' and high == 0
        else:
            matches = [f for f in supported if _matches_bug(f, oracle_turn['bug'])]
            fp = len(findings) - len(matches)
            high = sum(f['priority'] in ('P1', 'P2') and not _matches_bug(f, oracle_turn['bug'])
                       for f in supported) + findings.count(None)
            success = verdict is not None and verdict[1] == 'request-changes' and bool(matches) and high <= 1
        return {'success': bool(success), 'fp': int(fp), 'detail': 'verdict and finding checks'}
    if role == 'tester':
        return _tester_success(oracle_turn, workspace, pristine)
    raise ValueError(f'Unknown role: {role}')


def delivered(role, oracle_turn, parent_reply: str, workspace: Path) -> bool:
    if role == 'scout':
        # Token boundaries prevent 14 from being delivered by 142 (or an identifier suffix).
        reply = _normal(parent_reply)
        return any(re.search(r'(?<!\w)' + re.escape(answer) + r'(?![\w-])', reply)
                   for answer in _accepted_answers(oracle_turn))
    if role == 'reviewer':
        verdict = oracle_turn['verdict']
        if not re.search(r'(?<![\w-])' + re.escape(verdict) + r'(?![\w-])', parent_reply.casefold()):
            return False
        if verdict == 'approve':
            return True
        bug = oracle_turn['bug']
        citations = re.finditer(r'([^\s:|`\'"\[\]()<>*]+):([0-9]+)(?![0-9])', parent_reply)
        return (any(_matches_path(match[1], bug['file'])
                    and abs(_line_number(match[2]) - bug['line']) <= 2 for match in citations)
                and any(term in parent_reply.casefold() for term in bug['terms']))
    if role == 'tester':
        return _safe_file(workspace, _test_identity(oracle_turn)[0]) is not None
    raise ValueError(f'Unknown role: {role}')


def _unemphasize(value):
    for marker in ('**', '__', '*', '_'):
        if value.startswith(marker) and value.endswith(marker) and len(value) > 2 * len(marker):
            return value[len(marker):-len(marker)]
    return value


def route(arm, delegation, oracle_role):
    if arm not in ARMS or oracle_role not in ROLES:
        raise ValueError('Unknown arm or role')
    if arm != 'B-native':
        role = delegation.get('teammate')
        return 'correct' if role == oracle_role else 'wrong' if role else 'unspecified'
    first = delegation.get('goal', '').split('\n', 1)[0].strip()
    # Recognize emphasis on the line, label, or name without changing the fallback.
    punctuation = '.!?,;:'
    clean = _unemphasize(first.rstrip(punctuation)).rstrip(punctuation)
    label, separator, name = clean.partition(':')
    name = _unemphasize(name.strip().rstrip(punctuation)).rstrip(punctuation)
    explicit = separator and _unemphasize(label).casefold() == 'role' and re.fullmatch(r'\S+', name)
    if explicit:
        role = name.casefold()
    else:
        words = re.findall(r'\b(?:scout|reviewer|tester)\b', first.casefold())
        role = words[0] if len(words) == 1 else None
    return 'correct' if role == oracle_role else 'wrong' if role else 'unspecified'
