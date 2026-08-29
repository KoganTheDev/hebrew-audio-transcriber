"""
Tests for core/power.py.

The point of this module is that it can NEVER break a transcription, so
most of what is worth testing is its failure paths: a non-Windows host, a
ctypes build with no windll, and a Windows call that is rejected. Those are
all simulated by patching _set_thread_execution_state or sys.platform,
because none of them can be produced on the machine running these tests.
"""

import sys

import pytest

from speech_to_text.core import power


def test_acquire_asks_for_a_continuous_system_required_hold():
    """
    The flag combination is the whole behaviour, so pin it exactly.

    ES_SYSTEM_REQUIRED without ES_CONTINUOUS resets after a single idle
    tick, which would be useless for a run measured in tens of minutes.
    """
    seen = []
    original = power._set_thread_execution_state
    power._set_thread_execution_state = lambda flags: seen.append(flags) or 1
    try:
        assert power.acquire("test") is True
    finally:
        power._set_thread_execution_state = original
    assert seen == [power.ES_CONTINUOUS | power.ES_SYSTEM_REQUIRED]


def test_release_clears_with_continuous_alone():
    """Clearing keeps ES_CONTINUOUS and drops the requirement bits."""
    seen = []
    original = power._set_thread_execution_state
    power._set_thread_execution_state = lambda flags: seen.append(flags) or 1
    try:
        power.release("test", acquired=True)
    finally:
        power._set_thread_execution_state = original
    assert seen == [power.ES_CONTINUOUS]


def test_release_is_a_no_op_when_the_hold_was_never_taken():
    """
    Callers release from a finally without knowing whether acquire worked,
    so releasing a hold that does not exist must not touch the API at all.
    """
    seen = []
    original = power._set_thread_execution_state
    power._set_thread_execution_state = lambda flags: seen.append(flags) or 1
    try:
        power.release("test", acquired=False)
    finally:
        power._set_thread_execution_state = original
    assert seen == []


def test_non_windows_host_returns_none_without_touching_ctypes(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert power._set_thread_execution_state(power.ES_CONTINUOUS) is None


def test_a_raising_api_is_swallowed_not_propagated(monkeypatch):
    """
    A missing windll or a loader error must not reach the caller: the worst
    acceptable outcome is an unprotected run, never a failed transcription.
    """
    monkeypatch.setattr(sys, "platform", "win32")

    class Boom:
        def __getattr__(self, name):
            raise AttributeError("no windll in this build")

    monkeypatch.setitem(sys.modules, "ctypes", Boom())
    assert power._set_thread_execution_state(power.ES_CONTINUOUS) is None


def test_windows_null_return_is_treated_as_failure():
    """
    Windows signals failure with NULL, which is indistinguishable from a
    real previous state of 0. Treating 0 as failure risks one spurious
    debug line; treating it as success would claim a hold that isn't there.
    """
    original = power._set_thread_execution_state
    power._set_thread_execution_state = lambda flags: None
    try:
        assert power.acquire("test") is False
    finally:
        power._set_thread_execution_state = original


def test_context_manager_releases_even_when_the_body_raises():
    """An exception mid-run must not leave sleep suppressed for the process."""
    seen = []
    original = power._set_thread_execution_state
    power._set_thread_execution_state = lambda flags: seen.append(flags) or 1
    try:
        with pytest.raises(RuntimeError):
            with power.keep_system_awake("test"):
                raise RuntimeError("boom")
    finally:
        power._set_thread_execution_state = original
    assert seen == [power.ES_CONTINUOUS | power.ES_SYSTEM_REQUIRED, power.ES_CONTINUOUS]


def test_context_manager_yields_and_still_runs_when_the_hold_is_refused():
    """
    A machine that cannot be kept awake must still transcribe. The body runs
    either way; the yielded flag only reports what happened.
    """
    ran = []
    original = power._set_thread_execution_state
    power._set_thread_execution_state = lambda flags: None
    try:
        with power.keep_system_awake("test") as acquired:
            ran.append(acquired)
    finally:
        power._set_thread_execution_state = original
    assert ran == [False]
