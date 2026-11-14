"""trust_notice_routing: completion notices go to the assigning chat without a session check (operator opt-in)."""
import threading

import pytest

from test_v020 import start, result


def trusted(rig, monkeypatch, *, notify=True):
    calls = []
    rig.raw.update(notify_on_completion=notify, trust_notice_routing=True)
    rig.host.ctx.inject_message = lambda content, **kwargs: calls.append((content, kwargs)) or True
    scheduled = []
    monkeypatch.setattr(threading.Timer, 'start', lambda timer: scheduled.append(timer))
    return calls


def test_trusted_notice_is_delivered_without_session_binding(rig, monkeypatch):
    calls = trusted(rig, monkeypatch)
    assert rig.host.notice_session_id('anything') is None  # stock host: binding unavailable
    monkeypatch.setattr(rig.host, 'completion_target', lambda: ('chat-key', False))
    run_id = start(rig)
    receipt = result(rig, run_id)
    receipt.summary = 'CHILD OUTPUT must not be in the notice'
    rig.service.finalize(run_id, receipt, notify=True)
    rig.service._flush_notice('owner')
    assert len(calls) == 1
    text, kwargs = calls[0]
    assert 'worker finished' in text and run_id in text and 'teammate_check' in text
    assert 'CHILD OUTPUT' not in text and kwargs['role'] == 'user' and kwargs['session_key'] == 'chat-key'
    with rig.store() as store:
        assert store.get(run_id, 'owner')['notified_at'] is not None


def test_notice_goes_to_the_chat_recorded_at_assignment(rig, monkeypatch):
    calls = trusted(rig, monkeypatch)
    # The assigning chat, as the host sees it during teammate_assign (no global session vars touched).
    monkeypatch.setattr(rig.host, 'completion_target', lambda: ('durable-chat-key', False))
    run_id = start(rig)
    monkeypatch.setattr(rig.host, 'completion_target', lambda: (None, False))  # completion thread: no context
    rig.service.finalize(run_id, result(rig, run_id), notify=True)
    rig.service._flush_notice('owner')
    assert calls and calls[0][1]['session_key'] == 'durable-chat-key'


@pytest.mark.parametrize('cli', [False, True])
def test_run_with_no_recorded_chat(rig, monkeypatch, cli):
    # A cron turn (or any turn without a session key) records no chat. Only a classic-CLI process,
    # which queues key-less injections into its own REPL, may still get the notice.
    calls = trusted(rig, monkeypatch)
    monkeypatch.setattr(rig.host, 'completion_target', lambda: (None, cli))
    monkeypatch.setattr(rig.host, 'cli_attached', lambda: cli)
    run_id = start(rig)
    rig.service.finalize(run_id, result(rig, run_id), notify=True)
    rig.service._flush_notice('owner')
    if not cli:
        assert not calls
        with rig.store() as store:
            assert store.get(run_id, 'owner')['notified_at'] is None
        return
    assert len(calls) == 1 and calls[0][1]['session_key'] is None and run_id in calls[0][0]


def test_runs_from_two_chats_on_one_conversation_notify_each_chat(rig, monkeypatch):
    # /resume from another chat, /resume --all, --cross-room or /handoff can point two chat keys at one session.
    calls = trusted(rig, monkeypatch)
    monkeypatch.setattr(rig.host, 'completion_target', lambda: ('chat-a', False))
    run_a = start(rig)
    monkeypatch.setattr(rig.host, 'completion_target', lambda: ('chat-b', False))
    run_b = start(rig)
    for run_id in (run_a, run_b):
        rig.service.finalize(run_id, result(rig, run_id), notify=True)
    rig.service._flush_notice('owner')
    sent = {kwargs['session_key']: text for text, kwargs in calls}
    assert sorted(sent) == ['chat-a', 'chat-b']
    assert run_a in sent['chat-a'] and run_b not in sent['chat-a']
    assert run_b in sent['chat-b'] and run_a not in sent['chat-b']


@pytest.mark.parametrize('trust', [True, False])
def test_session_change_between_assignment_and_finish(rig, monkeypatch, trust):
    # A gateway /new, /reset or /resume keeps the chat's session key and points it at another conversation.
    calls = trusted(rig, monkeypatch)
    rig.raw['trust_notice_routing'] = trust
    monkeypatch.setattr(rig.host, 'completion_target', lambda: ('chat-key', False))
    run_id = start(rig)
    monkeypatch.setattr(rig.host, 'notice_session_id', lambda key=None: 'new-conversation')
    receipt = result(rig, run_id)
    receipt.summary = 'CHILD OUTPUT must not be in the notice'
    rig.service.finalize(run_id, receipt, notify=True)
    rig.service._flush_notice('owner')
    if not trust:  # without the opt-in, the session check drops the notice
        assert not calls
        return
    # Trusted: the notice follows the key into the chat's current conversation, as one line with no result text.
    assert len(calls) == 1 and calls[0][1]['session_key'] == 'chat-key'
    text = calls[0][0]
    assert f'worker finished (run {run_id}, succeeded)' in text and 'CHILD OUTPUT' not in text
    # The new conversation cannot read the run; it stays with the conversation that assigned it.
    assert rig.service.check('new-conversation', run_id)['error'] == 'unknown_run'
    assert rig.service.check('owner', run_id)['ok'] is not False


def test_trusted_needs_completion_notices_on(rig, monkeypatch):
    calls = trusted(rig, monkeypatch, notify=False)
    run_id = start(rig)
    rig.service.finalize(run_id, result(rig, run_id), notify=True)
    rig.service._flush_notice('owner')
    assert not calls
    assert rig.service.roster('owner', False)['features']['push_completion']['status'] == 'off'


def test_run_already_read_gets_no_notice(rig, monkeypatch):
    calls = trusted(rig, monkeypatch)
    run_id = start(rig)
    rig.service.finalize(run_id, result(rig, run_id), notify=True)
    rig.service.check('owner', run_id)
    rig.service._flush_notice('owner')
    assert not calls


def test_roster_reports_trusted_routing(rig, monkeypatch):
    trusted(rig, monkeypatch)
    push = rig.service.roster('owner', False)['features']['push_completion']
    assert push['status'] == 'on' and 'trusted routing' in push['reason'] and 'allow_gateway_injection' in push['reason']


def test_without_trust_stock_hosts_stay_unsupported(rig, monkeypatch):
    calls = trusted(rig, monkeypatch)
    rig.raw['trust_notice_routing'] = False
    assert rig.service.roster('owner', False)['features']['push_completion']['status'] == 'unsupported'
    run_id = start(rig)
    rig.service.finalize(run_id, result(rig, run_id), notify=True)
    rig.service._flush_notice('owner')
    assert not calls


@pytest.mark.parametrize('value', ['true', 1, None])
def test_trust_notice_routing_must_be_boolean(plugin, value):
    from hermes_teammates.teammates_config import parse
    config = parse({'trust_notice_routing': value})
    assert config['trust_notice_routing'] is False and any('trust_notice_routing' in e for e in config['config_errors'])
