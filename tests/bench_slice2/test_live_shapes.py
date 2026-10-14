"""Live GLM qualification shapes (live-run003): harness-control denial evidence, effective delegate_task role."""
import json
from pathlib import Path

import pytest

from test_fix_r1 import adapter
from bench.slice2 import hermes


def _hidden_without_session_cat(adapter):
    target = hermes.ROOT/'bench/slice2/proofs.py'
    row = next(e for e in adapter.events if e.get('tool') == 'read_file'
               and hermes.read_target(e, adapter.run/'work') == target)
    row.update(success=False, denied=False, error=None, not_found=True)
    terminal = next(e for e in adapter.events if e.get('tool') == 'terminal'
                    and hermes.read_target(e, adapter.run/'work') == target)
    # The agent probed with a shell loop: not attributable per target.
    terminal['args']['command'] = 'for t in a b; do cat "$t"; done'
    return target


@pytest.mark.parametrize('controls', ['both', 'before_only', 'after_only', 'none'])
def test_harness_controls_are_denial_evidence(adapter, monkeypatch, controls):
    target = _hidden_without_session_cat(adapter)
    calls = []
    def stub(run, profile, targets):
        calls.append(1)
        phase = 'before' if len(calls) == 1 else 'after'
        deny = controls == 'both' or controls == phase + '_only'
        return [dict(path=str(t), success=False, error='EPERM' if deny else 'OTHER') for t in targets]
    monkeypatch.setattr(hermes, 'controls', stub)
    batch = adapter.execute()
    hidden = controls == 'both'
    assert ('missing file is not denial' in batch['audit']['errors']) is not hidden
    classified = json.loads((adapter.run/'classified-tool-receipts.json').read_text())
    receipt = next(e for e in classified if e.get('tool') == 'read_file'
                   and hermes.read_target(e, adapter.run/'work') == target)
    assert (receipt.get('error') == 'SANDBOX_HIDDEN') is hidden
    if hidden:
        assert receipt['control_denied'] is True
        # The agent's own terminal probe still did not prove inheritance for this target.
        assert batch['parent_denials'] is False


def test_control_evidence_never_excuses_a_successful_read(adapter):
    target = hermes.ROOT/'bench/slice2/proofs.py'
    row = next(e for e in adapter.events if e.get('tool') == 'read_file'
               and hermes.read_target(e, adapter.run/'work') == target)
    row.update(success=True, denied=False, error=None, not_found=False)
    assert 'successful protected read' in adapter.execute()['audit']['errors']


def test_denied_controls_requires_both_phases(tmp_path):
    a, b = tmp_path/'a', tmp_path/'b'
    before = [dict(path=str(a), success=False, error='EPERM'), dict(path=str(b), success=False, error='EACCES')]
    after = [dict(path=str(a), success=False, error='EPERM'), dict(path=str(b), success=True, error=None)]
    assert hermes.denied_controls(before, after) == frozenset({Path(str(a))})


def _b_events(args):
    call = dict(tool='delegate_task', call_id='d1', args=args)
    return [dict(kind='batch', session_id='p', calls=[dict(tool='read_file', call_id='r1', args={'path': 'x'}), call]),
            dict(kind='pre_tool_call', session_id='p', tool='delegate_task', call_id='d1', args=args)]


@pytest.mark.parametrize('extra,ok', [({}, 1), ({'role': None}, 1), ({'role': ''}, 1), ({'role': 'leaf'}, 1),
                                      ({'background': None}, 1), ({'background': False}, 1),
                                      ({'role': 'orchestrator'}, 0), ({'background': True}, 0)])
def test_b_fanout_uses_effective_role_and_background(extra, ok):
    payloads = [f'brief\n\ngoal {i}\nScope: s{i}' for i in range(4)]
    args = dict(tasks=[dict(goal=p) for p in payloads], **extra)
    assert hermes.fanout_recipe(_b_events(args), 'p', 'B-briefed', payloads) == ok


def test_b_fanout_task_role_orchestrator_rejected():
    payloads = [f'brief\n\ngoal {i}\nScope: s{i}' for i in range(4)]
    args = dict(tasks=[dict(goal=p, role='orchestrator' if i == 0 else None) for i, p in enumerate(payloads)])
    assert hermes.fanout_recipe(_b_events(args), 'p', 'B-briefed', payloads) == 0


def test_probe_instruction_requires_one_plain_cat_per_call(tmp_path):
    text = hermes.qualification_recipe('C', tmp_path, [tmp_path/'t'])['parent']
    assert 'one target per tool call' in text and 'no loop, pipe' in text
