"""Offline relay framing; synthetic results only, no model calls."""
import json

import pytest

from test_v020 import result
from test_kanban_lane import create


TEXT = 'Finding: example.py:7 — keep "quoted" evidence\nVerdict: needs work\n補足: café'


def finish(rig, run_id, text):
    receipt = result(rig, run_id)
    receipt.summary = text
    return rig.service.finalize(run_id, receipt)


@pytest.mark.parametrize('consumer', ['teammate_assign', 'teammate_wait', 'teammate_check'])
@pytest.mark.parametrize('text', [TEXT, '日本語\n"引用"', TEXT + '界' * 9000],
                         ids=['multiline', 'unicode', 'ledger-clipped'])
def test_finished_wire_preserves_summary_and_adds_relay(rig, monkeypatch, consumer, text):
    from hermes_teammates.teammates_tools import handler
    if consumer == 'teammate_assign':
        monkeypatch.setattr(rig.service, 'start_monitor', lambda row, *a: finish(rig, row['run_id'], text))
        args = dict(teammate='worker', goal='synthetic task', wait_seconds=1)
    else:
        run_id = rig.service.assign('owner', 'worker', 'synthetic task')['run_id']
        finish(rig, run_id, text)
        args = dict(run_ids=[run_id], wait_seconds=0) if consumer == 'teammate_wait' else dict(run_id=run_id)
    wire = handler(consumer, lambda: rig.service)(args, session_id='owner')
    parsed = json.loads(wire)
    row = parsed['done'][0] if consumer == 'teammate_wait' else parsed
    assert row['summary'] == text[:8000]
    assert row['summary_chars'] == len(text)
    assert row['summary_clipped'] is (len(text) > 8000)
    guidance = row['relay_instruction']
    assert 'verbatim' in guidance and 'citations' in guidance and 'verdict' in guidance
    assert guidance in wire  # The guidance is readable directly, without another JSON decoding layer.
    assert '日本語' in wire or '補足' in wire
    assert '\\n' in wire and '\\"' in wire  # Summary stays a valid JSON string, decoded exactly above.
    if row['summary_clipped']:
        assert 'clipped' in guidance and 'incomplete' in guidance
    if consumer != 'teammate_check':
        assert 'goal' not in row


def test_wait_and_roster_use_their_existing_budgets(rig):
    ids = []
    for _ in range(16):
        run_id = rig.service.assign('owner', 'worker', 'goal')['run_id']
        finish(rig, run_id, '語' * 8000)
        ids.append(run_id)
    rows = rig.service.wait('owner', ids, wait_seconds=0)['done']
    assert len(rows) == 16
    for row in rows:
        assert row['summary'] == '語' * 1500
        assert row['summary_chars'] == 8000 and row['summary_clipped']
        assert 'incomplete' in row['relay_instruction']
    roster = rig.service.roster('owner')
    assert len(roster['runs']) == 16  # Same retained count as base a2fb2a3.
    assert len(json.dumps(roster, ensure_ascii=False)) <= 16000
    guidance = roster['relay_instruction']
    assert 'verbatim' in guidance and 'previews' in guidance and 'clipped' in guidance
    assert 'teammate_check' in guidance and 'full' in guidance
    for row in roster['runs']:
        assert row['summary'] == '語' * 300 and row['summary_clipped']
        assert 'relay_instruction' not in row


@pytest.mark.parametrize('text', [None, ''])
def test_pending_empty_and_unknown_results_do_not_invite_relay(rig, text):
    run_id = rig.service.assign('owner', 'worker', 'goal')['run_id']
    assert 'relay_instruction' not in rig.service.check('owner', run_id)
    finish(rig, run_id, text)
    assert 'relay_instruction' not in rig.service.check('owner', run_id)
    assert rig.service.check('foreign', run_id)['error'] == 'unknown_run'


@pytest.mark.parametrize('clipped', [False, True])
def test_followup_plain_text_preserves_result_and_marks_ledger_clipping(rig, clipped):
    rig.raw['followup_context_chars'] = 12000
    run_id = rig.service.assign('owner', 'worker', 'old goal')['run_id']
    text = TEXT + ('界' * 9000 if clipped else '')
    finish(rig, run_id, text)
    rig.service.assign('owner', 'worker', 'next goal', follow_up=True)
    context = rig.lifecycle.requests[-1].context
    assert text[:8000] in context
    assert 'Prior results are quoted verbatim below; continue from them.\n' in context
    assert 'Relay results verbatim.' not in context
    assert ('Result (clipped; incomplete):' in context) is clipped
    assert len(context) <= 30000


@pytest.mark.parametrize('clipped,budget', [(False, 110), (True, 130)])
def test_followup_omits_result_when_clipping_exhausts_budget(rig, clipped, budget):
    rig.raw['followup_context_chars'] = budget
    run_id = rig.service.assign('owner', 'worker', 'old goal')['run_id']
    finish(rig, run_id, 'x' * (9000 if clipped else 1000))
    assert rig.service.check('owner', run_id)['summary_clipped'] is clipped
    assert rig.service.assign('owner', 'worker', 'next goal', follow_up=True)['ok']
    context = rig.lifecycle.requests[-1].context
    for line in context.splitlines():
        assert line.strip() not in ('Result:', 'Result (clipped; incomplete):')
    assert 'Previous assignments:' not in context


@pytest.mark.parametrize('size', [0, 4500, 9000])
def test_kanban_summary_and_additive_relay_receipt(rig, monkeypatch, size):
    calls = []
    monkeypatch.setattr(rig.host, 'request_review', lambda *a, **kw: (calls.append(kw) or (True, 'ok')))
    card = create(rig)
    run_id = rig.service.assign('owner', 'worker', 'goal', kanban_task=card)['run_id']
    text = TEXT + '語' * size
    finish(rig, run_id, text)
    payload = calls[0]
    assert payload['summary'] == text[:4000]
    meta = payload['metadata']['hermes_teammates']
    assert meta['run_id'] == run_id and meta['result_hash']
    assert meta['summary_chars'] == len(text)
    assert meta['summary_clipped'] is (len(text) > 4000)
    assert 'verbatim' in meta['relay_instruction']
    if meta['summary_clipped']:
        assert 'incomplete' in meta['relay_instruction']


def test_tool_and_roster_guidance(plugin, rig):
    from hermes_teammates.teammates_tools import render_roster, schema
    for name in ('teammate_assign', 'teammate_wait', 'teammate_check'):
        assert 'verbatim' in schema(name)['description']
    text = render_roster(rig.service.roster('owner'))
    assert 'verbatim' in text and 'clipped' in text
