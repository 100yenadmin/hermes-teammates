"""Deterministic r3 graders; submitted tests run on pristine isolated variants."""
import ast
import functools
import json
import os
import re
import shlex
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
_FINDING = re.compile(r'^- ([^\s:|]+):([0-9]+)(?:-([0-9]+))? \| (P[123]) \| ([^|]+) \| (.+)$')
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


def _plain(line, keep_bullet=False):
    line = line.strip()
    if not keep_bullet and line.startswith(('- ', '* ', '+ ', '> ')):
        line = line[2:]
    return line.replace('*', '').replace('`', '').lstrip('#').lstrip()


def _content(text):
    """Success-only prose plus string leaves of a terminal JSON object."""
    decoder = json.JSONDecoder()
    candidates = re.finditer(r'(?m)^[ \t]*(?=\{)', text)
    for attempt, candidate in enumerate(candidates):
        if attempt == 50:
            break
        idx = candidate.end()
        try:
            value, end = decoder.raw_decode(text, idx)
        except (ValueError, RecursionError):
            continue
        remainder = text[end:].strip()
        if remainder == '```':
            remainder = ''
        if remainder or not isinstance(value, dict):
            continue
        lines = [line for line in text[:idx].splitlines() if line.strip() not in ('```', '```json')]

        def leaves(obj, key=''):
            if isinstance(obj, dict):
                for name, item in obj.items():
                    leaves(item, name)
            elif isinstance(obj, list):
                for item in obj:
                    leaves(item, key)
            elif isinstance(obj, str):
                verdict = obj.strip().casefold().removeprefix('verdict:').strip()
                if key.casefold() == 'verdict' and verdict in ('approve', 'request-changes'):
                    lines.append('VERDICT: ' + verdict)
                else:
                    lines.extend(obj.splitlines())

        try:
            leaves(value)
        except RecursionError:
            return dict(lines=text.splitlines(), envelope=False)
        return dict(lines=lines, envelope=True)
    return dict(lines=text.splitlines(), envelope=False)


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
        line = _plain(re.sub(r'^\d+[.)]\s+', '', line.strip()), keep_bullet=True)
        candidate = (re.match(r'^- [^\s:|]+:[0-9]', line)
                     or re.search(r'\|\s*P[123]\s*\|', line)
                     or re.match(r'^\[?P[123]\]?(?:\s*[:|)\]—–-]|\s+(?!(?:and|or)\b)[^\s/,])', _plain(line)))
        if candidate:
            match = _FINDING.fullmatch(line)
            start = _line_number(match[2]) if match else 0
            end = _line_number(match[3]) if match and match[3] else start
            rows.append(None if match is None or end < start else
                        {'file': match[1], 'line': start, 'line_from': start, 'line_to': end,
                         'priority': match[4], 'problem': match[5], 'fix': match[6]})
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
        args = receipt.get('args')
        command = (args if isinstance(args, dict) else {}).get('command', '')
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


def _invokes_pytest(command):
    if not isinstance(command, str):
        return False
    if '\n' in command:
        return any(_invokes_pytest(line) for line in command.splitlines())
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|')
        lexer.whitespace_split = True
        words = list(lexer)
    except ValueError:
        return False
    segments, segment = [], []
    for word in words:
        if word in (';', '&&', '||', '|', '&'):
            segments.append(segment)
            segment = []
        else:
            segment.append(word)
    segments.append(segment)
    for tokens in segments:
        if tokens and tokens[0] == 'env':
            tokens = tokens[1:]
        while tokens and re.match(r'^\w+=', tokens[0]):
            tokens = tokens[1:]
        if not tokens:
            continue
        executable = PurePosixPath(tokens[0]).name
        if executable in ('pytest', 'py.test'):
            return True
        if re.fullmatch(r'python(?:[0-9]+(?:\.[0-9]+)*)?', executable):
            if any(tokens[i:i + 2] == ['-m', 'pytest'] for i in range(1, len(tokens) - 1)):
                return True
    return False


def _node_receipt(receipts, node):
    for receipt in receipts:
        args = receipt.get('args')
        if (receipt.get('tool') != 'terminal'
                or not _invokes_pytest((args if isinstance(args, dict) else {}).get('command', ''))):
            continue
        result = receipt.get('result_text', '')
        try:
            envelope = json.loads(result)
        except (ValueError, TypeError):
            result = result.replace('\\n', '\n') if isinstance(result, str) else ''
        else:
            if isinstance(envelope, dict):
                if envelope.get('error'):
                    continue
                result = envelope.get('output', '')
        if not isinstance(result, str):
            continue
        lines = [line.strip() for line in result.splitlines()]
        if any(line.startswith('ERROR ') or line.startswith('ERROR collecting')
               or ' error' in line.casefold() and (line.startswith('=') or re.match(r'^[0-9]+ ', line))
               for line in lines):
            continue
        for line in lines:
            match = re.fullmatch(r'(?:FAILED (\S+)|(\S+) FAILED(?:\s+\[\s*\d+%\])?)(?: - .*)?', line)
            failed = (match[1] or match[2]) if match else ''
            if failed == node or failed.endswith('/' + node):
                return True
    return False


def check_rules(role, oracle_turn, text, delta, receipts, workspace: Path) -> list[bool]:
    lines, paths = _lines(text), _paths(delta)
    last = lines[-1] if lines else ''
    if role == 'scout':
        cites = list(_citations(text))
        # Every bracketed source must be a citation, including malformed/unclosed brackets.
        without_cites = re.sub(r'\[docs/[^\[\]:\n]+:[0-9]+\]', '', text)
        valid = bool(cites) and '[' not in without_cites and ']' not in without_cites
        for file, line in cites:
            source = _safe_file(workspace, file)
            valid = valid and source is not None and 1 <= line <= len(source.read_text().splitlines())
        return [not paths, bool(valid), len(' '.join(lines[:-1]).split()) <= 80,
                bool(_ANSWER.fullmatch(_plain(last)))]
    if role == 'reviewer':
        findings = _findings(text)
        return [not paths, all(f is not None for f in findings), len(findings) <= 5,
                bool(_VERDICT.fullmatch(_plain(last)))]
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
                any(_plain(line) == 'RED: ' + node for line in lines)
                and (_red_receipt(receipts, file) or _node_receipt(receipts, node)),
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


@functools.lru_cache(maxsize=None)
def _mechanism_patterns(terms):
    patterns = []
    for term in terms:
        prefix = term.endswith('*')
        body = term[:-1] if prefix else term
        before = r'(?<!\w)' if re.match(r'\w', body[0]) else ''
        after = r'(?!\w)' if not prefix and re.match(r'\w', body[-1]) else ''
        patterns.append(re.compile(before + re.escape(body) + after))
    return tuple(patterns)


def _names_mechanism(text, terms):
    text = text.casefold().replace('’', "'").replace('*', '').replace('`', '')
    return any(pattern.search(text) for pattern in _mechanism_patterns(tuple(terms)))


def _on_locus(finding, bug):
    return (finding is not None and _matches_path(finding['file'], bug['file'])
            and finding['line_from'] <= bug['line'] + 2 and finding['line_to'] >= bug['line'] - 2)


def _matches_bug(finding, bug):
    return (_on_locus(finding, bug) and finding['line_to'] - finding['line_from'] <= 4
            and finding['priority'] in ('P1', 'P2')
            and _names_mechanism(finding['problem'] + ' ' + finding['fix'], bug['terms']))


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


def _tester_success(oracle, workspace, pristine, support=()):
    file, _, node = _test_identity(oracle)
    submitted = _safe_file(workspace, file)
    if submitted is None:
        return {'success': False, 'fp': None, 'detail': 'submitted test absent or unsafe'}
    # Snapshot submitted bytes once; buggy and fixed trees get identical support.
    content = submitted.read_bytes()
    # Files this turn added or changed under tests/ (the rules allow them) travel with the test; src/ and
    # everything an earlier turn left behind stay pristine.
    extras = {}
    for relative in support:
        parts = PurePosixPath(relative).parts
        if relative == file or not parts or parts[0] != 'tests' or '..' in parts:
            continue
        source = _safe_file(workspace, relative)
        if source is not None and source.is_file():
            extras[relative] = source.read_bytes()
    venv = ensure_bench_python()
    python = venv / 'bin/python'
    SCRATCH.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='grade-', dir=SCRATCH) as directory:
        root = Path(directory)
        outcomes = []
        for label in ('buggy', 'fixed'):
            work = root / label / 'work'
            shutil.copytree(pristine, work, ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
            for relative, data in [*extras.items(), (file, content)]:
                (work / relative).parent.mkdir(parents=True, exist_ok=True)
                (work / relative).write_bytes(data)
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


def child_success(role, oracle_turn, text, workspace: Path, pristine: Path, receipts, support=()) -> dict:
    if role == 'scout':
        lines = _content(text)['lines']
        answers = {_normal(match[1]) for line in lines
                   if (match := re.fullmatch(r'ANSWER: (.+)', _plain(line)))}
        citation = oracle_turn['citation']
        valid_cite = any(file == citation['file'] and abs(line - citation['line']) <= 2
                         and _safe_file(workspace, file) is not None for file, line in _citations('\n'.join(lines)))
        success = bool(answers) and all(answer in _accepted_answers(oracle_turn) for answer in answers) and valid_cite
        return {'success': bool(success), 'fp': None, 'detail': 'answer and planted citation' if success else 'answer or citation mismatch'}
    if role == 'reviewer':
        lines = _content(text)['lines']
        verdicts = {match[1] for line in lines if (match := _VERDICT.fullmatch(_plain(line)))}
        verdict = next(iter(verdicts)) if len(verdicts) == 1 else None
        findings, seen = [], set()
        bug = oracle_turn.get('bug')
        for finding in _findings('\n'.join(lines)):
            if finding is None:
                findings.append(None)
                continue
            path = bug['file'] if bug and _matches_path(finding['file'], bug['file']) else finding['file']
            content = ' '.join((finding['problem'] + ' ' + finding['fix']).casefold().split())
            key = (path, finding['line_from'], finding['line_to'], finding['priority'], content)
            if key not in seen:
                seen.add(key)
                findings.append(finding)
        supported = [finding for finding in findings if finding is not None]
        # fp retains candidates minus matches; values are not comparable with identity ef7ecd76.
        if oracle_turn['verdict'] == 'approve':
            fp = len(findings)
            high = sum(f['priority'] in ('P1', 'P2') for f in supported) + findings.count(None)
            success = verdict == 'approve' and high == 0
        else:
            matches = [f for f in supported if _matches_bug(f, oracle_turn['bug'])]
            fp = len(findings) - len(matches)
            high = sum(f['priority'] in ('P1', 'P2') and not _matches_bug(f, oracle_turn['bug'])
                       for f in supported) + findings.count(None)
            success = verdict == 'request-changes' and bool(matches) and high <= 1
        return {'success': bool(success), 'fp': int(fp), 'detail': 'verdict and finding checks'}
    if role == 'tester':
        return _tester_success(oracle_turn, workspace, pristine, support)
    raise ValueError(f'Unknown role: {role}')


_NEGATIONS = {"not", "no", "never", "don't", "dont", "cannot", "can't", "won't", "wouldn't",
              "shouldn't", "isn't", "without"}


def _negated(text, start):
    clause = re.split(r'[.!?;:,\n—–]|\bbut\b', text[:start])[-1]
    words = re.findall(r"\b[\w']+\b", clause)
    return any(word in _NEGATIONS for word in words[-3:])


def delivered(role, oracle_turn, parent_reply: str, workspace: Path) -> bool:
    reply = parent_reply.casefold().replace('’', "'").replace('*', '').replace('`', '')
    if role == 'scout':
        answers = [_normal(_plain(line).removeprefix('answer: ')) for line in reply.splitlines()
                   if re.fullmatch(r'answer: .+', _plain(line))]
        if answers:
            reply = answers[-1]
        # Token boundaries prevent 14 from being delivered by 142 (or an identifier suffix).
        reply = re.sub(r'[^\S\n]+', ' ', reply)
        return any(not _negated(reply, match.start()) for answer in _accepted_answers(oracle_turn)
                   for match in re.finditer(r'(?<!\w)' + re.escape(answer) + r'(?![\w-])', reply))
    if role == 'reviewer':
        verdict = oracle_turn['verdict']
        explicit = [match[1].replace(' ', '-') for line in reply.splitlines()
                    if (match := re.fullmatch(r'verdict\s*[:—-]\s*(approve|request-changes|request changes)\s*', _plain(line)))]
        stance = explicit[-1] if explicit else None
        if not explicit:
            for match in re.finditer(r'(?<!\w)(request-changes|request changes|requests changes|requested changes|requesting changes|changes requested|approve|approved|approves)(?!\w)', reply):
                if not _negated(reply, match.start()):
                    stance = 'approve' if match[1] in ('approve', 'approved', 'approves') else 'request-changes'
                    break
        if stance != verdict:
            return False
        if verdict == 'approve':
            return True
        bug = oracle_turn['bug']
        citations = re.finditer(r'([^\s:|`\'"\[\]()<>*]+):([0-9]+)(?![0-9])', reply)
        return (any(_matches_path(match[1], bug['file'])
                    and abs(_line_number(match[2]) - bug['line']) <= 2 for match in citations)
                and _names_mechanism(reply, bug['terms']))
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
