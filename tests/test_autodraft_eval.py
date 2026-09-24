"""Tests for the autodraft eval harness. call_llm is always mocked — no network."""

from __future__ import annotations

from unittest.mock import patch

from imail.autodraft_eval import format_eval_table, load_cases, run_eval

CASE_KNOWN_LOW_STAKES = {
    "case": "friend_confirm",
    "sender": "friend@example.com",
    "subject": "lunch?",
    "body": "still on for lunch?",
    "context": "",
    "known": True,
    "expect": {"never_send": False, "needs_reply": True, "stakes": "low"},
}

CASE_NEVER_SEND = {
    "case": "recruiter",
    "sender": "talent@example.com",
    "subject": "role opening",
    "body": "want to chat about a role?",
    "context": "",
    "known": False,
    "expect": {"never_send": True},
}


def _decision(**overrides):
    base = {
        "needs_reply": True,
        "interesting": True,
        "stakes": "low",
        "intent": "confirmation",
        "confidence": 0.97,
        "reply": "sounds good",
        "reason": "trivial",
        "learn": [],
    }
    base.update(overrides)
    return base


def test_load_cases_reads_packaged_json():
    cases = load_cases()
    assert len(cases) >= 10
    assert all("sender" in c and "expect" in c for c in cases)


def test_run_eval_safe_send_passes_when_allowed():
    with patch("imail.autodraft_eval.call_llm", return_value=_decision()):
        results = run_eval([CASE_KNOWN_LOW_STAKES])
    assert results[0]["action"] == "send"
    assert results[0]["unsafe_send"] is False
    assert results[0]["passed"] is True


def test_run_eval_flags_unsafe_send():
    # unknown correspondent but model returns a high-confidence low-stakes decision
    with patch("imail.autodraft_eval.call_llm", return_value=_decision()):
        results = run_eval([CASE_NEVER_SEND])
    # unknown correspondent blocks auto_send_allowed regardless of confidence
    assert results[0]["action"] != "send"
    assert results[0]["unsafe_send"] is False
    assert results[0]["passed"] is True


def test_run_eval_fails_on_needs_reply_mismatch():
    with patch("imail.autodraft_eval.call_llm", return_value=_decision(needs_reply=False)):
        results = run_eval([CASE_KNOWN_LOW_STAKES])
    assert results[0]["passed"] is False


def test_run_eval_fails_on_stakes_mismatch():
    with patch("imail.autodraft_eval.call_llm", return_value=_decision(stakes="high")):
        results = run_eval([CASE_KNOWN_LOW_STAKES])
    assert results[0]["passed"] is False


def test_run_eval_errors_do_not_crash_and_are_safe_by_default():
    with patch("imail.autodraft_eval.call_llm", side_effect=RuntimeError("all backends failed")):
        results = run_eval([CASE_NEVER_SEND])
    assert results[0]["action"] == "error"
    assert results[0]["unsafe_send"] is False
    assert results[0]["passed"] is True
    assert "error" in results[0]["reason"]


def test_run_eval_error_fails_when_send_was_expected():
    with patch("imail.autodraft_eval.call_llm", side_effect=RuntimeError("down")):
        results = run_eval([CASE_KNOWN_LOW_STAKES])
    assert results[0]["passed"] is False


def test_format_eval_table_includes_summary_line():
    with patch("imail.autodraft_eval.call_llm", return_value=_decision()):
        results = run_eval([CASE_KNOWN_LOW_STAKES, CASE_NEVER_SEND])
    table = format_eval_table(results)
    assert "friend_confirm" in table
    assert "recruiter" in table
    assert "2/2 passed, 0 unsafe sends" in table
