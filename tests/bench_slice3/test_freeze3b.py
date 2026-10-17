"""Offline freeze follow-ups, using only synthetic inputs."""
import itertools
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from utils import fast_safe_load

from bench.slice3 import analysis, grade, identity, run, session
from .test_analysis import dataset
from .test_run import synthetic_qualification
from .test_session import passing_controls


@pytest.fixture
def scout_rules(tmp_path):
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs/guide.md').write_text('Synthetic value.\n')
    def check(extra):
        text = extra + '\n[docs/guide.md:1]\nANSWER: synthetic'
        return grade.check_rules('scout', {}, text, {}, [], tmp_path)[1]
    return check


@pytest.mark.parametrize('label', ['[docs/guide.md:1]', '[label]', 'label [nested] text'])
def test_rule2_rejects_bracketed_markdown_link_text(scout_rules, label):
    assert not scout_rules(f'[{label}](docs/guide.md)')


@pytest.mark.parametrize('items', list(itertools.permutations(
    ['docs/guide.md', 'generic', '[docs/guide.md:1]'])))
def test_rule2_outer_array_ignores_non_source_strings_in_any_order(scout_rules, items):
    assert scout_rules(json.dumps(items))


@pytest.mark.parametrize('bad', ['[docs/guide.md]', '[docs/guide.md:1-2]', '[docs/guide.md:1'])
@pytest.mark.parametrize('reverse', [False, True])
def test_rule2_nested_sources_checked_independently(scout_rules, bad, reverse):
    items = ['[docs/guide.md:1]', bad]
    assert not scout_rules(json.dumps([items[::-1] if reverse else items]))


@pytest.mark.parametrize('missing', [None, 'teammates_roster', 'teammate_check', 'teammate_wait',
                                   'teammate_message', 'teammate_stop', 'teammate_assign'])
@pytest.mark.parametrize('search', [False, True])
def test_off_requires_full_plugin_tool_surface(synthetic_qualification, missing, search):
    tools = fast_safe_load((identity.ROOT / 'plugin.yaml').read_text())['provides_tools']
    tools = [tool for tool in tools if tool != missing] + ['read_file', 'terminal']
    if search:
        tools.append('tool_search')
    turns = synthetic_qualification['C']
    home = Path(turns[0]['invocation']).parents[1] / 'hermes'
    (home / 'config.yaml').write_text(json.dumps({'tools': {'tool_search': {'enabled': 'off'}}}))
    for turn in turns:
        turn['inventories']['parent_tools'] = [dict(tools=tools)]
    assert run.qualification(synthetic_qualification)['checks']['C:parent_tools']['pass_'] is (
        missing is None and not search)


def test_frozen_c_auto_visibility(synthetic_qualification):
    config = json.loads((identity.IDENTITY.parent / 'configs.json').read_text())['C']
    assert config is not None
    assert 'tool_search' not in config.get('tools', {})
    turns = synthetic_qualification['C']
    home = Path(turns[0]['invocation']).parents[1] / 'hermes'
    (home / 'config.yaml').write_text(json.dumps(config))
    assert run.qualification(synthetic_qualification)['checks']['C:parent_tools']['pass_']
    turns[1]['inventories']['parent_tools'][0]['tools'].append('teammate_assign')
    assert not run.qualification(synthetic_qualification)['checks']['C:parent_tools']['pass_']


@pytest.mark.parametrize('bad', ['missing', None, '', 'wrong'])
def test_analysis_requires_identity_on_every_row(monkeypatch, bad):
    monkeypatch.setattr(analysis, 'RESAMPLES', 2)
    rows = [row | {'identity': identity.verify()} for row in dataset()]
    if bad == 'missing':
        rows[-1].pop('identity')
    else:
        rows[-1]['identity'] = bad
    with pytest.raises(ValueError, match='identity'):
        analysis.analyze(rows)


def test_analysis_rejects_unscheduled_case(monkeypatch):
    monkeypatch.setattr(analysis, 'RESAMPLES', 2)
    rows = [row | {'identity': identity.verify()} for row in dataset()]
    with pytest.raises(ValueError, match='scheduled'):
        analysis.analyze(rows, cases=['case0'])


@pytest.mark.parametrize('orphan_kind', [None, 'request_start', 'usage'])
@pytest.mark.parametrize('owned_child', [False, True])
def test_session_child_tokens_unknown_for_unowned_receipts(
        tmp_path, lane_f, monkeypatch, orphan_kind, owned_child):
    def setup(case, arm, directory):
        for name in ('work', 'home', 'hermes', 'probe', 'tmp', 'turns'):
            (directory / name).mkdir(parents=True)
        return tmp_path / 'synthetic-venv'
    monkeypatch.setattr(session, 'setup', setup)
    monkeypatch.setattr(session, 'sandbox_profile', lambda *a, **kw: '(version 1)\n')
    monkeypatch.setattr(session.subprocess, 'run', passing_controls)
    stream = '\n'.join(json.dumps(row) for row in [
        dict(subtype='init', session_id='p'), dict(type='result', text='Synthetic reply')])
    monkeypatch.setattr(session.subprocess, 'Popen', lambda *a, **kw: SimpleNamespace(
        returncode=0, communicate=lambda **kw: (stream.encode(), b'')))
    rows = [dict(id='p', parent_session_id=None)]
    if owned_child:
        rows.append(dict(id='child', parent_session_id='p', source='subagent'))
    monkeypatch.setattr(session, 'read_state', lambda path: (rows, [], {}))
    receipts = [] if orphan_kind is None else [dict(
        kind=orphan_kind, session_id='unowned', request_id='r', retry=0, attempt=0)]
    monkeypatch.setattr(session, 'records', lambda path: receipts if path.name == 'usage.jsonl' else [])
    dest = tmp_path / 'session'
    turns = session._run_session('dev0', 'C', dest, fake_base_url='http://127.0.0.1:1', turn_limit=1)
    expected = 0 if orphan_kind is None else None
    assert analysis.token_total(turns[0]['child_usage']) == expected
    saved = json.loads((dest / 'turns.jsonl').read_text())
    assert analysis.token_total(saved['child_usage']) == expected
    errors = json.loads((dest / 'reconciliation.json').read_text())['errors']
    assert ('unowned session' in errors) is (orphan_kind is not None)
