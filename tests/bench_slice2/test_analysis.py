import json
import sqlite3

import pytest

from bench.slice2.accounting import Observer, accounting, reconcile
from bench.slice2.audit import audit_reads, qualify
from bench.slice2.budget import admit
from bench.slice2.grade import JudgeHarness, blind, score
from bench.slice2.stats import analyze, verdict
from bench.slice2.protocol import schedule


def usage(n=10):
    return dict(input_tokens=n, output_tokens=2, cache_read_tokens=3,
                cache_write_tokens=0, reasoning_tokens=1, prompt_tokens=n+3)


def test_request_observer_and_absence(tmp_path):
    path = tmp_path / 'requests.jsonl'
    observer = Observer(path)
    for sid, rid, aux, u in [('p','1',None,usage()), ('c','2',None,usage(20)),
                             ('p','3','compression',usage(5)), ('p','4',None,None)]:
        kw = dict(session_id=sid, api_request_id=rid, retry_count=0, aux_task=aux)
        observer.hook('pre_auxiliary_call' if aux else 'pre_api_request', **kw)
        observer.hook('post_auxiliary_call' if aux else 'post_api_request', usage=u, **kw)
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    assert len([r for r in rows if r['kind']=='usage']) == 4
    m = accounting(rows, {'p':None,'c':'p'}, 'p')
    assert m['parent_tokens'] is None and m['child_tokens']==25
    assert m['parent_api_calls']==3 and m['parent_peak_prompt_tokens'] is None
    rows = [r for r in rows if r['request_id']!='4']
    m = accounting(rows, {'p':None,'c':'p'}, 'p')
    assert m['parent_tokens']==25 and m['parent_peak_prompt_tokens']==13
    assert m['total_tokens']==50  # reasoning is not additive
    assert accounting(rows, {}, 'p')['parent_tokens'] is None


def test_reconciliation_dedup_and_missing(tmp_path):
    o=Observer(tmp_path/'u')
    for sid in ('p','c'):
        o.hook('pre_api_request', session_id=sid,api_request_id=sid)
        o.hook('post_api_request',session_id=sid,api_request_id=sid,usage=usage())
    rows=[json.loads(x) for x in (tmp_path/'u').read_text().splitlines()]
    db=[dict(id=sid,parent_session_id=None if sid=='p' else 'p',api_call_count=1,**usage()) for sid in ('p','c')]
    receipt=dict(run_id='r',session_id='c',tokens_input=10,tokens_output=2,
                 tokens_cache_read=3,tokens_cache_write=0,tokens_reasoning=1)
    assert reconcile(rows,db,[receipt,receipt],'p')['pass']
    assert not reconcile(rows,db,[receipt|{'tokens_input':11}],'p')['pass']
    assert not reconcile(rows,db,[{k:v for k,v in receipt.items() if k!='tokens_cache_write'}],'p')['pass']
    assert not reconcile(rows,db,[],'p',require_plugin=True)['pass']


def test_audit_controls(tmp_path):
    allowed=tmp_path/'run/file'; protected=tmp_path/'oracle'
    assert audit_reads([dict(path=str(allowed),success=True)], [protected], tmp_path/'run')['pass']
    assert not audit_reads([dict(path=str(protected),success=True)], [protected], tmp_path/'run')['pass']
    assert not audit_reads([dict(path=str(protected),success=False,error='ENOENT')], [protected], tmp_path/'run')['pass']
    assert not audit_reads([], [protected], tmp_path/'run')['pass']


def claim(cause, status, bug=None, affirmative=True):
    return dict(cause=cause,status=status,bug_id=bug,affirmative=affirmative,evidence='causal supported trigger')


def test_semantic_scoring():
    oracle={'bugs':[dict(id='a',cross_file=True),dict(id='b',cross_file=False)]}
    findings=[claim('root','supported','a'),claim('root','supported','a'),
              claim('suspicious but correct','unsupported',affirmative=False),
              claim('false causal defect','unsupported'),claim('false causal defect','unsupported'),
              claim('novel','unplanted')]
    s=score(findings,oracle,verified_unplanted={'novel':'receipt'})
    assert (s['tp'],s['fp'],s['duplicates'],s['recall'],s['cross_file_recall'])==(1,1,2,.5,1)
    assert s['unplanted']==['novel']
    assert score(findings,oracle,failed=True,verified_unplanted={'novel':'receipt'})['precision']==0
    with pytest.raises(ValueError): score([claim('novel','unplanted')],oracle)
    with pytest.raises(ValueError): score([claim('huh','ambiguous')],oracle)


def test_judge_controls_and_blinding():
    from bench.slice2.grade import controls
    expected=controls()
    calls=[]
    def fake(request):
        calls.append(request)
        return next(c['expected'] for c in expected if c['answer']==request['answer'])
    h=JudgeHarness(fake)
    assert h.qualify()['pass'] and len(calls)==6
    assert all('untrusted' in c['system'].lower() and c['delimited_answer'] for c in calls)
    assert '<END_ANSWER>' not in calls[-1]['delimited_answer'].splitlines()[1]
    broken=JudgeHarness(lambda request: {'findings':[], 'followed_instruction':True})
    assert not broken.qualify()['pass']
    with pytest.raises(ValueError): broken.grade('text',{},'case')
    answers,mapping=blind([{'arm':'C','cell':'r','answer':'teammate_wait session_id=abc Found root'},
                          {'arm':'B-briefed','cell':'b','answer':'delegate_task Found root'}])
    assert 'C' not in json.dumps(answers) and 'teammate' not in json.dumps(answers)
    assert len(mapping)==2


def metrics(recall=.8, tokens=100):
    return dict(recall=recall,precision=.9,parent_tokens=tokens,parent_peak_prompt_tokens=50,
                parent_api_calls=4,total_tokens=tokens*2,cross_file_recall=recall)


def test_statistics_and_three_verdicts():
    rows=[c|dict(status='COMPLETE',metrics=metrics(),integrity=True,accounting=True) for c in schedule()]
    r=analyze(rows,qualified=True,grades_frozen=True)
    assert r['verdict']=='CLOSES GAP' and r['resamples']==20000
    assert r['contrasts']['parent_tokens']['point']==1
    assert analyze(rows[:-1],qualified=True,grades_frozen=True)['verdict']=='INCONCLUSIVE'
    rows[0]['status']='FAILED'
    assert analyze(rows,qualified=True,grades_frozen=True)['verdict']=='INCONCLUSIVE'
    bounds={'recall':[-.04,0], 'precision':[-.04,0], 'parent_tokens':[1,1.1],
            'parent_peak_prompt_tokens':[1,1.1], 'parent_api_calls':[0,1]}
    assert verdict(bounds)=='CLOSES GAP'
    assert verdict(bounds|{'recall':[-.2,-.06]})=='DOES NOT CLOSE GAP'
    assert verdict(bounds|{'parent_tokens':[1.11,1.2]})=='DOES NOT CLOSE GAP'
    assert verdict(bounds|{'recall':[-.06,0]})=='INCONCLUSIVE'


def test_budget_admission():
    rows=[c|dict(wall_s=30,requests=5,status='COMPLETE') for c in schedule('calibration')]
    limits={'plan':'GLM coding plan','request_limit':1000,'used_requests':50,
            'grading_requests':50,'grading_wall_s':100,'reproducer_wall_s':10,'human_wall_s':100}
    assert admit(rows,limits)['decision']=='ADMIT'
    assert admit(rows,limits|{'request_limit':1})['decision']=='DEFER'
    assert admit(rows[:-1],limits)['decision']=='DEFER'
    assert admit(rows,limits|{'human_wall_s':30000})['decision']=='DEFER'
