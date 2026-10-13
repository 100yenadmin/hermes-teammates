import json

import pytest

from bench.drivers.hermes_cell import TASK
from bench.tasks.t1.grade import grade

ORACLE = json.loads((TASK / 'oracle.json').read_text()) if (TASK / 'oracle.json').exists() else None


def finding(bug, offset=0, word=None):
    return f"src/{bug['file']}:{bug['line'] + offset} — {word or bug['keywords'][0]} bug — fix it"


def test_perfect_review():
    result = grade('\n'.join(finding(b) for b in ORACLE['bugs']), ORACLE)
    assert (result['recall'], result['precision'], result['f1'], result['pass']) == (1, 1, 1, True)


@pytest.mark.parametrize('offset,word,match', [(3, 'batch', True), (-3, 'batch', True), (4, 'batch', False), (0, 'style', False)])
def test_line_and_class_required(offset, word, match):
    result = grade(finding(ORACLE['bugs'][0], offset, word), ORACLE)
    assert result['bugs_found'] == int(match)
    assert result['false_positives'] == int(not match)


def test_decoy_counts_false_positive():
    bug, decoy = ORACLE['bugs'][0], ORACLE['decoys'][0]
    result = grade(finding(bug) + f"\n{decoy['file']}:{decoy['line']} — range is wrong — change endpoint", ORACLE)
    assert result['bugs_found'] == 1
    assert result['false_positives'] == 1
    assert result['precision'] == .5


def test_duplicates_do_not_inflate_score():
    result = grade('\n'.join([finding(ORACLE['bugs'][0])] * 3), ORACLE)
    assert result['bugs_found'] == 1
    assert result['duplicates'] == 2
    assert result['precision'] == 1


def test_empty_and_failed_outputs_score_zero():
    assert grade('', ORACLE)['f1'] == 0
    result = grade('\n'.join(finding(b) for b in ORACLE['bugs']), ORACLE, failed=True)
    assert result['f1'] == 0 and not result['pass']


def test_seeded_corpus(tmp_path):
    from bench.tasks.t1.fixture_gen import fixture_hash, generate
    assert generate(tmp_path / 'src') == ORACLE
    assert fixture_hash(tmp_path) == fixture_hash(TASK / 'fixture')
    assert all(150 <= len(p.read_text().splitlines()) <= 250 for p in (tmp_path / 'src').glob('*.py'))
