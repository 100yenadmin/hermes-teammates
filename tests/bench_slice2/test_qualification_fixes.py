"""Bench-only qualification rules; fake tool hooks/processes, no Hermes required."""
import json

import pytest

from test_fix_r1 import adapter
from test_prequal import probe
from bench.slice2 import hermes
from bench.slice2.audit import audit_reads


@pytest.mark.parametrize('damage', [None, 'before', 'after', 'no_terminal', 'foreign_session',
                                  'foreign_target', 'terminal_other', 'terminal_not_cat',
                                  'success', 'no_not_found'])
def test_hidden_read_requires_all_proofs(adapter, monkeypatch, damage):
    target = hermes.ROOT/'bench/slice2/proofs.py'
    row = next(e for e in adapter.events if e.get('tool') == 'read_file'
               and hermes.read_target(e, adapter.run/'work') == target)
    row.update(success=False, denied=False, error=None, not_found=True)
    terminal = next(e for e in adapter.events if e.get('tool') == 'terminal'
                    and hermes.read_target(e, adapter.run/'work') == target)
    calls = []
    def readable(path, mode):
        if path == target:
            calls.append(path)
            return damage != ('before' if len(calls) == 1 else 'after')
        return True
    monkeypatch.setattr(hermes.os, 'access', readable)
    if damage == 'no_terminal': adapter.events.remove(terminal)
    if damage == 'foreign_session': terminal['session_id'] = 'foreign'
    if damage == 'foreign_target': terminal['args']['command'] = 'cat /other'
    if damage == 'terminal_other': terminal['error'] = 'OTHER'
    if damage == 'terminal_not_cat': terminal['args']['command'] = f'echo {target}'
    if damage == 'success': row['success'] = True
    if damage == 'no_not_found': row.pop('not_found')
    batch = adapter.execute()
    # The adapter's harness controls deny every protected target before and after, so the session's own
    # cat is no longer required for the blocked-read classification (it still is for parent_denials).
    terminal_damage = damage in {'no_terminal', 'foreign_session', 'foreign_target', 'terminal_not_cat'}  # a failed cat with an unexplained error stays an audit error
    expected = ([] if damage is None or terminal_damage else ['successful protected read'] if damage == 'success'
                else ['missing file is not denial'])
    assert set(batch['audit']['errors']) == set(expected)
    assert batch['parent_denials'] is (damage is None)
    assert len(calls) == 2, 'outside readability must be checked before AND after'
    if damage is None or terminal_damage:
        classified = json.loads((adapter.run/'classified-tool-receipts.json').read_text())
        receipt = next(e for e in classified if e.get('tool') == 'read_file'
                       and hermes.read_target(e, adapter.run/'work') == target)
        assert receipt['error'] == 'SANDBOX_HIDDEN' and receipt['denied'] is True


def test_nonprotected_not_found_is_unchanged(adapter):
    adapter.events.append(dict(kind='post_tool_call', session_id='p', tool='read_file',
                               args={'path': str(adapter.run/'work/missing')},
                               success=False, denied=False, error=None, not_found=True))
    assert adapter.execute()['audit']['pass']
    assert adapter.events[-1]['denied'] is False


@pytest.mark.parametrize('missing', ['before', 'after'])
def test_missing_outside_file_is_not_hidden_denial(tmp_path, missing):
    target = tmp_path/'protected'
    if missing == 'after': target.write_text('synthetic')
    before = hermes.outside_readability([target])
    if missing == 'before': target.write_text('synthetic')
    else: target.unlink()
    after = hermes.outside_readability([target])
    read = dict(kind='post_tool_call', session_id='s', tool='read_file',
                args={'path': str(target)}, success=False, denied=False, error=None, not_found=True)
    terminal = dict(kind='post_tool_call', session_id='s', tool='terminal',
                    args={'command': f'cat {target}'}, success=False, denied=True, error='EPERM')
    classified = hermes.classify_hidden_reads([read, terminal], [target], tmp_path, before, after)
    assert classified[0] == read
    assert not hermes.read_coverage(classified, [target], tmp_path, denied=True)
    assert audit_reads([dict(path=str(target), success=False, error='OTHER')], [target], tmp_path)['errors'] == ['missing file is not denial']


def test_hidden_error_cannot_satisfy_terminal_coverage(tmp_path):
    target = tmp_path/'protected'
    row = dict(tool='terminal', args={'command': f'cat {target}'}, success=False,
               denied=True, error='SANDBOX_HIDDEN', not_found=True)
    assert not hermes.read_coverage([row], [target], tmp_path, denied=True, kinds=('terminal',))


def test_hidden_read_audit_accepts_denial_but_rejects_success(tmp_path):
    target = tmp_path/'protected'
    row = dict(path=str(target), success=False, error='SANDBOX_HIDDEN')
    assert audit_reads([row], [target], tmp_path)['pass']
    assert audit_reads([row | {'success': True}], [target], tmp_path)['errors'] == ['successful protected read']


def test_probe_read_file_records_only_scalar_not_found(probe):
    lifecycle, rows = probe
    lifecycle.invoke_hook('post_tool_call', session_id='p', tool_name='read_file',
                          args={'path': '/protected'}, status='error', error_type='tool_error',
                          result=json.dumps({'not_found': True, 'error': 'File not found: /protected'}))
    assert rows[-1]['not_found'] is True
    assert rows[-1]['result'] == {} and 'File not found' not in json.dumps(rows[-1])


@pytest.mark.parametrize('tool', ['teammate_assign', 'teammate_check', 'teammate_wait'])
@pytest.mark.parametrize('damage', [None, 'exception', 'timeout', 'ok_false', 'error',
                                  'missing_ok', 'invalid_json', 'blocked', 'ok_exception', 'ok_timeout'])
def test_teammate_structured_success(probe, tool, damage):
    lifecycle, rows = probe
    result = dict(ok=True, error=None, run_id='r', pending=[], timed_out=False,
                  done=[dict(run_id='r', status='succeeded', summary='Permission denied')])
    status, error_type = 'error', 'tool_error'
    if damage in {'exception', 'timeout'}: error_type = damage
    if damage in {'ok_exception', 'ok_timeout'}: status, error_type = 'ok', damage[3:]
    if damage == 'ok_false': result['ok'] = False
    if damage == 'missing_ok': result.pop('ok')
    if damage == 'error': result['error'] = 'broken'
    if damage == 'blocked': status = 'blocked'
    lifecycle.invoke_hook('post_tool_call', session_id='p', tool_name=tool, args={},
                          status=status, error_type=error_type,
                          result='bad JSON' if damage == 'invalid_json' else json.dumps(result))
    receipt = rows[-1]
    assert receipt['success'] is (damage is None)
    assert receipt['denied'] is False and receipt['error'] is None
    assert (receipt['status'], receipt['error_type']) == (status, error_type)
    assert 'Permission denied' not in json.dumps(receipt)


@pytest.mark.parametrize('tool', ['teammate_assign', 'teammate_check', 'teammate_wait', 'delegate_task'])
def test_successful_summary_is_not_os_denial(probe, tool):
    lifecycle, rows = probe
    lifecycle.invoke_hook('post_tool_call', session_id='p', tool_name=tool, args={},
                          status='ok', result=json.dumps(dict(ok=True, summary='EPERM EACCES Permission denied Operation not permitted')))
    assert rows[-1]['success'] is True and rows[-1]['denied'] is False


def test_terminal_permission_denied_is_still_eacces(probe):
    lifecycle, rows = probe
    lifecycle.invoke_hook('post_tool_call', session_id='p', tool_name='terminal',
                          args={'command': 'cat /protected'}, status='error', error_type='tool_error',
                          result=json.dumps(dict(exit_code=1, output='cat: /protected: Permission denied')))
    assert rows[-1]['success'] is False
    assert rows[-1]['denied'] is True and rows[-1]['error'] == 'EACCES'
