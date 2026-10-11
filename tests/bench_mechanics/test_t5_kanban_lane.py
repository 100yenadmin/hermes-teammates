"""M3: six real lane claims, five scripted files, one failure, no expired claims."""
import json
import time


def test_six_card_lane(mount, tmp_path, metrics):
    rig = mount({'max_live_runs': 3})
    rig.require_kanban()
    cards = [rig.card(f'Mechanics card {index}') for index in range(6)]
    pending, active, completed = list(enumerate(cards)), {}, {}
    claimed_expiry = {}
    started = time.monotonic()
    while pending or active:
        assert time.monotonic() - started < 60, 'six cards did not finish within 60s'
        while pending and len(active) < 3:
            index, task_id = pending.pop(0)
            path, content = tmp_path / f'card-{index}.txt', f'card {index}\n'
            assigned = rig.assign('a', 'fail' if index == 5 else 'succeed', label=f'card-{index}',
                                  path=str(path), content=content, token=f'card-{index}', kanban_task=task_id)
            assert assigned['ok'], assigned
            active[assigned['run_id']] = (index, task_id, path, content)
            with rig.host.connection() as conn:
                history = rig.host.kanban.list_runs(conn, task_id)
                assert len(history) == 1
                # Fast children may already have ended and cleared claim_expires.
                claimed_expiry[task_id] = history[0].claim_expires
        for run_id, item in list(active.items()):
            row = rig.check(run_id, wait_seconds=0.1)
            assert row['ok'], row
            if row['status'] != 'running':
                completed[run_id] = (item, row)
                del active[run_id]
        if active:
            time.sleep(0.02)
    elapsed = time.monotonic() - started
    statuses = []
    for run_id, ((index, task_id, path, content), row) in completed.items():
        card = rig.read_card(task_id)
        statuses.append(card.status)
        with rig.host.connection() as conn:
            history = rig.host.kanban.list_runs(conn, task_id)
            assert len(history) == 1
            run = history[0]
            assert card.current_run_id is None
            with rig.service.store_factory() as store:
                ledger = store.get(run_id, rig.parent.session_id)
                claim = json.loads(ledger['kanban_claim'])
            assert claim['kanban_run_id'] == run.id
            assert run.claim_lock == f'hermes-teammates:{run_id}'
            assert run.ended_at is not None and run.outcome in ('review_requested', 'blocked')
            assert run.claim_expires is None and card.claim_expires is None
            if claimed_expiry[task_id] is not None:
                assert run.ended_at <= claimed_expiry[task_id]
            events = conn.execute('SELECT kind FROM task_events WHERE task_id=?', (task_id,)).fetchall()
            assert not any('expir' in event[0] or 'reclaim' in event[0] for event in events)
            if index < 5:
                assert run.metadata['hermes_teammates']['run_id'] == run_id
        if index < 5:
            assert row['status'] == 'succeeded' and card.status == 'review' and run.summary
            assert path.read_text(encoding='utf-8') == content
        else:
            assert row['status'] == 'failed' and card.status == 'blocked' and run.summary
    assert statuses.count('review') == 5 and statuses.count('blocked') == 1
    metrics('M3', 'time_to_all_terminal', round(elapsed, 4), 'seconds')
    metrics('M3', 'review_cards', 5, 'cards')
    metrics('M3', 'blocked_cards', 1, 'cards')
    metrics('M3', 'expired_claims', 0, 'claims')
