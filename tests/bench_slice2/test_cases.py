import sys

import pytest

from bench.slice2.protocol import TASK
from bench.slice2.proofs import oracle, reproduce, variant

HIDDEN = (TASK/'hidden/oracles.json').exists()
pytestmark = pytest.mark.skipif(not HIDDEN, reason='hidden oracles are published after the scored run')
CASES = sorted(p.name for p in (TASK/'cases').iterdir())
BUGS = [(case, b['id']) for case in CASES for b in oracle(case)['bugs']] if HIDDEN else []


@pytest.mark.parametrize('case,bug_id',BUGS)
def test_planted_bug_red_then_green(case,bug_id,tmp_path):
    o=oracle(case)
    assert len(o['bugs'])==6 and len(o['decoys'])==4
    assert sum(b['cross_file'] for b in o['bugs'])>=2
    bug=next(b for b in o['bugs'] if b['id']==bug_id)
    bad=variant(case,tmp_path/'bad')
    red=reproduce(bad,bug['proof'],sys.executable)
    assert not red['passed'] and not red['invalid'], red
    good=variant(case,tmp_path/'good',bug=bug)
    green=reproduce(good,bug['proof'],sys.executable)
    assert green['passed'], green


@pytest.mark.parametrize('case',CASES)
def test_decoys_and_complete_reference(case,tmp_path):
    o=oracle(case)
    bad=variant(case,tmp_path/'bad')
    assert reproduce(bad,'\n'.join(o['decoys']),sys.executable)['passed']
    for i,proof in enumerate([b['proof'] for b in o['bugs']]+o['decoys']):
        good=variant(case,tmp_path/f'good{i}',corrected=True)
        assert reproduce(good,proof,sys.executable)['passed'], (case,i)
