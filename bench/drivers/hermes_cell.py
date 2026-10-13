"""One sandbox-exec + env -i subprocess per cell, adapted from core_tool_deferral.

No installed Hermes, auth adoption, dependency installation or host-home execution.
Only the GLM_API_KEY line is copied; no other live-home reads are permitted.
"""
import hashlib
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from bench.extract import extract, observed, probe_metrics
from bench.tasks.t1.fixture_gen import fixture_hash
from bench.tasks.t1.grade import grade

ROOT = Path(__file__).resolve().parents[2]
HERMES = Path('/Users/m1/repos/worktrees/hermes-main-venv')
HERMES_SHA = '3b63f7b0a4c7beb9eadbce2f15b9da75d01f5065'
PLUGIN_SHA = 'dc0aad69905739511c0888d009d6501dc015846a'
ENDPOINT = 'https://api.z.ai/api/coding/paas/v4'
MAX_TURNS, WALL_LIMIT, CHILD_TURNS = 24, 900, 250
QUOTA = re.compile(r'\b429\b|rate.?limit|quota|insufficient.?balance|balance.?limit|usage.?limit', re.I)
TASK = ROOT / 'bench/tasks/t1'


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def roster():
    from ruamel.yaml import YAML
    return YAML(typ='safe').load((ROOT / 'bench/roster.yaml').read_text())


def config(arm, model):
    value = {'model': {'provider': 'zai', 'default': model},
             'auth': {'adopt_external_logins': False}, 'security': {'allow_lazy_installs': False},
             'agent': {'max_turns': MAX_TURNS, 'api_max_retries': 1},
             'terminal': {'backend': 'local'}, 'compression': {'enabled': False},
             'delegation': {'max_concurrent_children': 4, 'oneshot_max_children': 4,
                            'max_iterations': CHILD_TURNS},
             'plugins': {'isolation': 'in_process', 'enabled': ['hermes-teammates'] if arm == 'C' else []}}
    if arm == 'C':
        value['plugins']['entries'] = {'hermes-teammates': {'settings': {'teammates': roster(), 'max_live_runs': 4}}}
    return value


def prompt(arm):
    text = (TASK / 'prompt.md').read_text()
    instructions = roster()['reviewer']['instructions']
    briefs = [f"{instructions} Assigned module: src/{p.name}." for p in sorted((TASK / 'fixture/src').glob('*.py'))]
    if arm == 'A':
        return text + '\nReview all modules yourself; no delegation.\n'
    if arm == 'B':
        mechanism = 'Call delegate_task once with tasks containing the following four goals (one worker per goal), role=leaf, background=false. Use the returned findings to produce your final answer.'
    else:
        mechanism = 'Assign all four goals to teammate reviewer before waiting. Then call teammate_check with wait_seconds=60 on every run; repeat until each is terminal. Use the returned findings to produce your final answer.'
    return text + '\n' + mechanism + '\nGoals (copy exactly):\n' + '\n'.join(briefs) + '\n'


def sandbox_profile(run):
    # Deny reads by default; no plugin checkout or published benchmark access.
    python_home = subprocess.check_output(
        [str(HERMES / '.venv/bin/python'), '-c', 'import sys; print(sys.base_prefix)'],
        text=True, env={'HERMES_DISABLE_LAZY_INSTALLS': '1'}).strip()
    directories = [run, python_home, HERMES / '.venv', '/System', '/usr/lib',
                   '/usr/share', '/bin', '/sbin', '/usr/bin', '/usr/sbin', '/dev']
    directories += [HERMES / name for name in
                    ('agent', 'hermes_cli', 'tools', 'hermes_platform', 'providers',
                     'gateway', 'cron', 'pm', 'assets', 'locales', 'hermes_agent.egg-info')]
    files = list(HERMES.glob('*.py')) + [Path('/'), HERMES / 'pyproject.toml',
             Path('/private/etc/resolv.conf'), Path('/private/etc/hosts'),
             Path('/private/etc/localtime'), Path('/private/etc/services')]
    reads = ' '.join(f'(subpath {json.dumps(str(Path(p).resolve()))})' for p in directories)
    reads += ' ' + ' '.join(f'(literal {json.dumps(str(p.resolve()))})' for p in files)
    parents = {str(parent) for p in directories + files + [Path(os.readlink(HERMES / '.venv/bin/python'))]
               for parent in Path(p).parents}
    metadata = ' '.join(f'(literal {json.dumps(p)})' for p in sorted(parents))
    return ('(version 1)\n(allow default)\n(deny file-read*)\n'
            f'(allow file-read* {reads})\n(allow file-read-metadata {metadata})\n'
            '(deny file-write*)\n'
            f'(allow file-write* (subpath {json.dumps(str(run.resolve()))}) '
            '(literal "/dev/null") (literal "/dev/zero") (literal "/dev/dtracehelper") '
            '(regex #"^/dev/tty") (regex #"^/dev/fd/"))\n'
            '(deny process-exec (literal "/usr/bin/security"))\n')


@contextmanager
def isolated(model, arm='A'):
    base = Path(os.environ.get('TMPDIR', tempfile.gettempdir())).resolve()
    run = Path(tempfile.mkdtemp(prefix='tmbench.', dir=base)).resolve()
    try:
        for folder in ('home', 'hermes/plugins', 'tmp', 'work', 'pycache'):
            (run / folder).mkdir(parents=True)
        # Exact authorized read: grep only the single key line, with mode 0600.
        envfile = run / 'hermes/.env'
        fd = os.open(envfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as out:
            subprocess.run(['/usr/bin/grep', '-E', '^GLM_API_KEY=', str(Path.home() / '.hermes/.env')], stdout=out, check=True)
            out.write(f'GLM_BASE_URL={ENDPOINT}\n'.encode())
        # JSON is valid YAML, and avoids requiring a separate YAML writer.
        (run / 'hermes/config.yaml').write_text(json.dumps(config(arm, model)))
        plugin = run / 'hermes/plugins/hermes-teammates'
        plugin.mkdir()
        for name in ('__init__.py', 'plugin.yaml', 'teammates_config.py', 'teammates_host.py',
                     'teammates_service.py', 'teammates_store.py', 'teammates_tools.py'):
            shutil.copy2(ROOT / name, plugin / name)
        shutil.copytree(ROOT / 'bench/probe', run / 'probe', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(ROOT / 'bench/preflight.py', run / 'preflight.py')
        shutil.copytree(TASK / 'fixture/src', run / 'work/src')
        (run / 'sb.sb').write_text(sandbox_profile(run))
        env = {'HOME': str(run / 'home'), 'USER': 'm1', 'LOGNAME': 'm1', 'LANG': 'en_US.UTF-8',
               'TMPDIR': str(run / 'tmp'), 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin',
               'HERMES_HOME': str(run / 'hermes'), 'HERMES_DISABLE_LAZY_INSTALLS': '1',
               'PYTHONPYCACHEPREFIX': str(run / 'pycache'), 'TERMINAL_HOME_MODE': 'profile',
               'TERMINAL_CWD': str(run / 'work'), 'HERMES_PLUGIN_PAYLOAD_MAX_CHARS': '2000000',
               'PYTHONPATH': f'{run / "probe"}:{HERMES}',
               'TMBENCH_PROBE': str(run / 'probe.jsonl')}
        launcher = ['/usr/bin/env', '-i', *[f'{k}={v}' for k, v in env.items()],
                    '/usr/bin/sandbox-exec', '-f', str(run / 'sb.sb'), str(HERMES / '.venv/bin/python')]
        yield run, launcher, sorted(env)
    finally:
        # This is a freshly created owned RUN only; never delete a caller-supplied path.
        shutil.rmtree(run)


def redact(data, run):
    for line in (run / 'hermes/.env').read_text().splitlines():
        if line.startswith('GLM_API_KEY='):
            key = line.partition('=')[2].strip().strip('"\'')
            if key:
                data = data.replace(key, '[REDACTED]')
    return data


def preflight(evidence):
    """Three same-endpoint 1-token probes; one quota retry after 60s, no alternate key."""
    with isolated('glm-5.3') as (run, launcher, _):
        completed = subprocess.run(launcher + [str(run / 'preflight.py')], cwd=run / 'work',
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=260, text=True)
        rows = json.loads(completed.stdout)
        write_json(evidence / 'preflight.json', rows)
        if any(row.get('quota_stop') for row in rows):
            return None, rows
        selected = next((m for m in ('glm-5.3', 'glm-5.2', 'glm-5.1')
                         if any(r['model'] == m and r['status'] == 200 for r in rows)), None)
        return selected, rows


def copy_db(source, target):
    if source.exists():
        with sqlite3.connect(f'{source.as_uri()}?mode=ro', uri=True) as src, sqlite3.connect(target) as dst:
            src.backup(dst)


def checkpoint_errors(function):
    def checked(arm, rep, model, evidence, attempt=1):
        destination = evidence / f'{arm}{rep}' / f'attempt{attempt}'
        receipt = destination / 'cell.json'
        if receipt.exists():
            return json.loads(receipt.read_text())
        try:
            return function(arm, rep, model, evidence, attempt)
        except Exception as error:
            if not destination.is_dir():
                raise
            row = {'cell': f'{arm}{rep}', 'arm': arm, 'rep': rep, 'model': model,
                   'attempt': attempt, 'status': 'FAILED', 'reason': 'harness_error',
                   'error_type': type(error).__name__, 'pass': False, 'workspace_unchanged': None,
                   'metrics': {k: observed(v) for k, v in
                               {'recall': 0, 'precision': 0, 'f1': 0, 'failures': 1}.items()}}
            write_json(receipt, row)
            return row
    return checked


@checkpoint_errors
def run_attempt(arm, rep, model, evidence, attempt=1):
    destination = evidence / f'{arm}{rep}' / f'attempt{attempt}'
    destination.mkdir(parents=True, exist_ok=False)
    with isolated(model, arm) as (run, launcher, env_names):
        query = run / 'prompt.txt'
        query.write_text(prompt(arm))
        toolsets = {'A': 'file,terminal', 'B': 'file,terminal,delegation', 'C': 'file,terminal,teammates'}[arm]
        command = launcher + ['-m', 'hermes_cli.main', 'chat', '-Q', '--query-file', str(query),
                              '--format', 'stream-json', '--ignore-rules', '--toolsets', toolsets,
                              '--max-turns', str(MAX_TURNS), '--provider', 'zai', '--model', model]
        started = time.time()
        write_json(destination / 'launch.json', {'started_at': started, 'env_names': env_names,
                   'arm': arm, 'rep': rep, 'model': model, 'fixture_hash': fixture_hash(TASK / 'fixture')})
        timeout, quota = False, False
        with (run / 'stream.jsonl').open('w') as stdout, (run / 'stderr.log').open('w') as stderr:
            process = subprocess.Popen(command, cwd=run / 'work', stdout=stdout, stderr=stderr,
                                       stdin=subprocess.DEVNULL, start_new_session=True)
            try:
                while process.poll() is None:
                    time.sleep(1)
                    if (run / 'probe.jsonl').exists():
                        quota = '"quota": true' in (run / 'probe.jsonl').read_text()
                    quota = quota or bool(QUOTA.search((run / 'stderr.log').read_text()))
                    timeout = time.time() - started >= WALL_LIMIT
                    if quota or timeout:
                        break
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        wall = time.time() - started
        stream = redact((run / 'stream.jsonl').read_text(), run)
        errors = redact((run / 'stderr.log').read_text(), run)
        quota = quota or bool(QUOTA.search(errors))
        (destination / 'stream.jsonl').write_text(stream)
        (destination / 'stderr.log').write_text(errors)
        if (run / 'probe.jsonl').exists():
            shutil.copy2(run / 'probe.jsonl', destination / 'probe.jsonl')
        # Preserve synthetic source before any extraction/grading can fail.
        source = run / 'work/src'
        source_present = source.is_dir() and not source.is_symlink()
        if source_present:
            shutil.copytree(source, destination / 'workspace/src', symlinks=True)
        write_json(destination / 'workspace-state.json', {'source_present': source_present})
        events = []
        for line in stream.splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        final = next((row for row in reversed(events) if row.get('type') == 'result'), {})
        root = next((row.get('session_id') for row in events if row.get('subtype') == 'init' and row.get('session_id')), final.get('session_id'))
        for name in ('state.db', 'data.db', 'kanban.db'):
            copy_db(run / 'hermes' / name, destination / name)
        copy_db(run / 'hermes/plugin-data/hermes-teammates/data.db', destination / 'ledger.db')
        extracted = extract(destination / 'state.db', destination / 'ledger.db', root)
        write_json(destination / 'state-extract.json', extracted)
        write_json(destination / 'ledger-extract.json', extracted['ledger'])
        text = final.get('text', '')
        reason = ('quota' if quota else 'timeout' if timeout else
                  'process_error' if process.returncode or final.get('exit_code') else
                  'workspace_missing' if not source_present else
                  'missing_final' if not text else 'missing_state' if not extracted['sessions'] else None)
        score = grade(text, json.loads((TASK / 'oracle.json').read_text()), failed=bool(reason))
        write_json(destination / 'grade.json', score)
        metrics = extracted['metrics'] | probe_metrics(destination / 'probe.jsonl', root)
        metrics.update({key: observed(score[key]) for key in ('bugs_found', 'bugs_planted', 'false_positives', 'recall', 'precision', 'f1')})
        metrics.update(wall_s=observed(wall), failures=observed(int(bool(reason))), timeouts=observed(int(timeout)))
        before, after = fixture_hash(TASK / 'fixture'), fixture_hash(run / 'work')
        row = {'cell': f'{arm}{rep}', 'arm': arm, 'rep': rep, 'attempt': attempt, 'model': model,
               'status': 'FAILED' if reason else 'COMPLETE', 'reason': reason, 'metrics': metrics,
               'pass': score['pass'], 'root_session_id': root, 'started_at': started, 'ended_at': time.time(),
               'fixture_hash': before, 'workspace_unchanged': before == after,
               'hermes_sha': HERMES_SHA, 'plugin_sha': PLUGIN_SHA, 'env_names': env_names,
               'config_hash': hashlib.sha256(json.dumps(config(arm, model), sort_keys=True).encode()).hexdigest()}
        write_json(destination / 'cell.json', row)
        return row
