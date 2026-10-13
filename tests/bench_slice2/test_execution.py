import json

import pytest

from bench.slice2.audit import qualify
from bench.slice2.protocol import ARMS, config, recipe
from bench.slice2.run import run_phase


def qualified_batch(arm,start=0):
    return dict(arm=arm,started=start,ended=start+1,peak_concurrency=4,fanout_batches=1,
                status='COMPLETE',integrity=True,recipe_valid=True,no_teammate_check=True,
                parent_max_turns=40,parent_compression=True,
                outside_readable=True,parent_denials=True,parent_allowed_read=True,
                accounting={'pass':True},audit={'pass':True},wait_complete=True,full_wait_ids=True,
                children=[dict(session_id=f'c{i}',completed=True,effective_launch='brief',wrapper='system',
                               matched_brief=True,tools=['file','terminal'],max_turns=250,compression=True,
                               os_denials_file=True,os_denials_terminal=True,allowed_read=True,sandbox_inherited=True)
                          for i in range(4)])


def test_qualification_rejects_inferred_controls():
    batches=[qualified_batch(a,i) for i,a in enumerate(ARMS)]
    assert qualify(batches)['pass']
    for field in ('fanout_batches','peak_concurrency','parent_denials','outside_readable','full_wait_ids'):
        bad=json.loads(json.dumps(batches)); bad[1][field]=False
        assert not qualify(bad)['pass'],field
    bad=json.loads(json.dumps(batches)); bad[0]['children'][0]['max_turns']=24
    assert not qualify(bad)['pass']
    bad=json.loads(json.dumps(batches)); bad[0]['children'][0]['matched_brief']=False
    assert not qualify(bad)['pass']


def test_fake_phase_path_and_resume(tmp_path):
    calls=[]
    def fake(launch,directory):
        calls.append(launch['cell'])
        assert len(list((directory/'work/src').glob('*.py')))==5
        assert not (directory/'work/hidden').exists()
        return launch|qualified_batch(launch['arm'],len(calls))|dict(status='COMPLETE',wall_s=30,requests=5)
    q=run_phase('qualification',tmp_path,fake)
    assert q['pass'] and len(calls)==2
    assert run_phase('qualification',tmp_path,fake)==q and len(calls)==2
    cells=run_phase('calibration',tmp_path,fake)
    assert len(cells)==8 and len(calls)==10
    assert (tmp_path/'audit-controls.json').exists()
    with pytest.raises(ValueError,match='Budget DEFER'): run_phase('scored',tmp_path,fake,{})
    limits={'plan':'GLM coding plan','request_limit':1000,'used_requests':10,
            'grading_requests':60,'grading_wall_s':100,'human_wall_s':100,'reproducer_wall_s':100}
    assert len(run_phase('scored',tmp_path,fake,limits))==40
    assert len(calls)==50


def test_interrupted_attempt_never_replayed(tmp_path):
    def crash(*args): raise RuntimeError('fake crash')
    with pytest.raises(RuntimeError): run_phase('qualification',tmp_path,crash)
    with pytest.raises(ValueError,match='Interrupted'): run_phase('qualification',tmp_path,crash)
    identity=tmp_path/'identity.json'; identity.write_text('{}')
    with pytest.raises(ValueError,match='identity drift'): run_phase('qualification',tmp_path,crash)


def test_live_adapter_has_no_implicit_admission(tmp_path,monkeypatch):
    from bench.slice2.hermes import execute
    monkeypatch.delenv('SLICE2_LIVE',raising=False)
    with pytest.raises(ValueError,match='disabled'): execute({},tmp_path)


def test_compression_and_tools_symmetric():
    b,c=[config(a) for a in ARMS]
    assert b['compression']==c['compression']=={'enabled':True}
    assert b['delegation']==c['delegation']
    assert 'bare' not in recipe('B-briefed')['parent']


def test_bootstrap_observer_failure_preserves_hooks(tmp_path):
    from types import SimpleNamespace
    from bench.slice2.accounting import install
    calls=[]
    lifecycle=SimpleNamespace(has_hook=lambda n:False,invoke_hook=lambda n,**k:calls.append(n))
    install(lifecycle,tmp_path/'absent/u')
    lifecycle.invoke_hook('pre_api_request',session_id='p',api_request_id='r')
    assert calls==['pre_api_request']


def test_blind_sample_is_required():
    from bench.slice2.grade import freeze_grades
    packet={'human_sample':['a'],'controls':{'pass':True}}
    with pytest.raises(ValueError): freeze_grades(packet,[])
    assert freeze_grades(packet,['a'])['frozen']
