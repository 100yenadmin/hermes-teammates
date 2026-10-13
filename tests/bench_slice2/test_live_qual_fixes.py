"""Fixes from the first live qualification attempt (2026-10-14): every batch died at import."""
from pathlib import Path

import pytest

from bench.drivers.hermes_cell import HERMES, sandbox_profile
from bench.slice2.hermes import classify


@pytest.mark.skipif(not (HERMES / '.venv/bin/python').exists(), reason='pinned Hermes checkout not present (CI)')
def test_sandbox_allows_every_hermes_runtime_package(tmp_path):
    # Hermes main imports its bundled `plugins` package at startup; a missing allow killed every cell.
    profile = sandbox_profile(tmp_path)
    for package in sorted(p for p in HERMES.iterdir() if (p / '__init__.py').exists()):
        if package.name in {'tests', 'evals'}:
            continue
        assert f'(subpath "{package.resolve()}")' in profile, package.name


def test_crash_before_any_model_call_is_a_harness_error_with_reason():
    stderr = 'Traceback (most recent call last):\n  File "x"\nModuleNotFoundError: No module named \'plugins\'\n'
    status, reason = classify(returncode=1, timeout=False, answer='', stderr=stderr, requests=0, quota=False, key='k')
    assert status == 'HARNESS_ERROR'
    assert reason == "ModuleNotFoundError: No module named 'plugins'"


def test_agent_failure_after_model_calls_stays_failed():
    status, reason = classify(returncode=1, timeout=False, answer='', stderr='RuntimeError: boom\n', requests=3, quota=False, key='k')
    assert status == 'FAILED' and reason == 'RuntimeError: boom'
    assert classify(returncode=0, timeout=False, answer='done', stderr='', requests=3, quota=False, key='k') == ('COMPLETE', None)
    assert classify(returncode=0, timeout=True, answer='done', stderr='', requests=3, quota=False, key='k')[0] == 'FAILED'
    assert classify(returncode=1, timeout=False, answer='', stderr='429 quota', requests=1, quota=True, key='k')[0] == 'QUOTA_STOP'


def test_reason_never_carries_the_key():
    status, reason = classify(returncode=1, timeout=False, answer='', stderr='ValueError: bad key sk-secret\n', requests=0, quota=False, key='sk-secret')
    assert 'sk-secret' not in reason
