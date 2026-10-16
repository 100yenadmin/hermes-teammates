"""Recorded model arguments stay raw; consumers treat non-dicts as empty."""
import json
from types import SimpleNamespace

import pytest

from bench.slice3 import grade, session
from bench.slice3.analysis import score_turn
from .test_session import passing_controls


# Shape from live-run003/scored/06-cinder-C/attempt1/run/turns/4/events.jsonl;
# values are synthetic, and the embedded fields must not become valid args.
LIST_ARGS = [dict(teammate='scout', goal='Synthetic goal', wait_seconds=9)]


@pytest.mark.parametrize('args', [LIST_ARGS, 'malformed', None])
def test_assign_wait_seconds_non_dict(args):
    calls = [dict(tool='teammate_assign', args=args),
             dict(tool='terminal', args=args)]
    assert session.assign_wait_seconds(calls) == [None]
    assert calls[0]['args'] is args


def test_task_dicts_non_dict():
    assert session._task_dicts(LIST_ARGS) == [{}]


def test_requested_goals_non_dict():
    assert session.requested_goals(LIST_ARGS) == set()


@pytest.mark.parametrize('consumer', [grade._red_receipt, grade._node_receipt])
def test_terminal_receipt_non_dict(consumer):
    node = 'tests/test_synthetic.py::test_regression'
    receipt = dict(tool='terminal', args=[dict(command='python -m pytest ' + node)],
                   result_text='FAILED ' + node + '\n1 failed in 0.1s', exit_code=1)
    assert consumer([receipt], node) is False
    assert isinstance(receipt['args'], list)


def test_session_extracts_and_grades_list_args(tmp_path, lane_f, monkeypatch):
    def setup(case, arm, run):
        for name in ('work', 'home', 'hermes', 'probe', 'tmp', 'turns'):
            (run / name).mkdir(parents=True)
        return tmp_path / 'synthetic-venv'

    monkeypatch.setattr(session, 'setup', setup)
    monkeypatch.setattr(session, 'sandbox_profile', lambda run, extra_read=(): '(version 1)\n')
    monkeypatch.setattr(session.subprocess, 'run', passing_controls)
    user = lane_f.load_case('dev0')['turns'][0]['text']
    call = dict(id='malformed-call', function=dict(name='teammate_assign',
                                                 arguments=json.dumps(LIST_ARGS)))
    rows = [dict(id='parent', parent_session_id=None)]
    messages = [dict(id=1, session_id='parent', role='user', content=user),
                dict(id=2, session_id='parent', role='assistant', tool_calls=[call])]
    monkeypatch.setattr(session, 'read_state', lambda path: (rows, messages, {}))

    def popen(command, **kwargs):
        # Pure fake launch: no CLI, socket, model, or provider request.
        env = kwargs['env']
        event = dict(kind='post_tool_call', session_id='parent', call_id='malformed-call',
                     tool='teammate_assign', args={}, result_text='Invalid arguments',
                     result=dict(error='Invalid arguments'))
        from pathlib import Path
        Path(env['SLICE3_EVENTS']).write_text(json.dumps(event) + '\n')
        stream = json.dumps(dict(type='result', text='Recorded malformed attempt', is_error=False))
        return SimpleNamespace(returncode=0, communicate=lambda **kw: (stream.encode(), b''))

    monkeypatch.setattr(session.subprocess, 'Popen', popen)
    turns = session._run_session('dev0', 'C', tmp_path / 'session',
                                 fake_base_url='http://127.0.0.1:1', turn_limit=1)
    assert len(turns) == 1
    turn = turns[0]
    assert turn['status'] == 'ok' and turn['infra_invalid'] is None
    assert turn['parent']['assign_wait_seconds'] == [None]
    assert turn['children'][0]['wait_seconds'] is None
    assert len(turn['children']) == 1 and turn['children'][0]['goal'] == ''
    assert turn['graded_child'] is None
    scored = score_turn(turn, {'role': 'scout'}, tmp_path, tmp_path)
    assert scored['success'] == scored['adherence_all'] == 0
    assert scored['infra_invalid'] is None
    recorded = json.loads((tmp_path / 'session/turns.jsonl').read_text())
    assert recorded == turn
    calls = session.turn_calls(messages, {'parent'}, user)
    assert calls[0]['args'] == LIST_ARGS


def test_raw_list_args_remain_matchable_and_recorded():
    call = dict(tool='teammate_assign', args=LIST_ARGS, session_id='parent',
                call_id='physical', entry_index=0)
    batch = dict(kind='batch', session_id='parent',
                 calls=[dict(call, call_id='bridge')])
    assert session.canonical_calls([call], [batch])[0]['call_id'] == 'bridge'
    event = dict(kind='post_tool_call', session_id='parent', tool='teammate_assign',
                 call_id='other', args=LIST_ARGS)
    assert session._claim([event], 'post_tool_call', call, {}, set(), False, {}) == 0
    assert session.child_receipts([event], 'parent')[0]['args'] == LIST_ARGS
