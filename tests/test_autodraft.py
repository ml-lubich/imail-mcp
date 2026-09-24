"""Tests for imail autodraft engine."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from imail.autodraft import (
    INTENT_CONFIRMATION,
    INTENT_DIRECT_INQUIRY,
    INTENT_RECRUITER,
    INTENT_SKIP,
    call_llm,
    classify_intent,
    process_inbox_autodraft,
    select_resume,
    strip_markdown,
)


def test_strip_markdown():
    raw = "**Bold** and *italic* and `code` and [Link](https://google.com) — dash"
    clean = strip_markdown(raw)
    assert "**" not in clean
    assert "*" not in clean
    assert "`" not in clean
    assert "Bold and italic and code and Link (https://google.com) - dash" == clean


def test_classify_intent_skip():
    assert classify_intent("no-reply@github.com", "Security alert") == INTENT_SKIP
    assert classify_intent("digest@substack.com", "Weekly newsletter") == INTENT_SKIP
    assert classify_intent("billing@stripe.com", "Your receipt") == INTENT_SKIP
    assert classify_intent("someone@example.com", "Your order has shipped") == INTENT_SKIP
    assert classify_intent("user@random.com", "Hello there") == INTENT_SKIP


def test_classify_intent_recruiter():
    sender = "recruiter@tundratechnical.com"
    subject = "Job opening for Senior Software Engineer"
    assert classify_intent(sender, subject) == INTENT_RECRUITER


def test_classify_intent_confirmation():
    sender = "friend@example.com"
    subject = "sounds good, see you tomorrow"
    assert classify_intent(sender, subject) == INTENT_CONFIRMATION


def test_classify_intent_inquiry():
    sender = "colleague@example.com"
    subject = "Can you send the project update?"
    assert classify_intent(sender, subject) == INTENT_DIRECT_INQUIRY


def test_classify_intent_skips_generic_blast_recruiters():
    assert classify_intent(
        "Ramdatt <ramdatt@kpg99.in>",
        "OPENING FOR Sr. Software Engineer, AI ::: REMOTE",
    ) == INTENT_SKIP
    assert classify_intent(
        "Lokesh Nag <lokesh.nag@excelonsolutions.com>",
        "Contract Accessibility Tester  122 E Brokaw Rd, San Jose, CA-95112 [ONSITE]",
    ) == INTENT_SKIP
    assert classify_intent(
        "Mayank <mayank.kushwah@rulesiq.com>",
        "IMMEDIATE INTERVIEW | OFFER ROLE | URGENT HIRING | Senior Full Stack Engineer",
    ) == INTENT_SKIP
    assert classify_intent(
        "Griffen Rude <grude@tundratechnical.com>",
        "Job with Meta",
    ) == INTENT_RECRUITER


def test_select_resume(tmp_path, monkeypatch):
    resumes_dir = tmp_path / "dev/resumes/resumes"
    ai_dir = resumes_dir / "resume_mlubich_ai"
    ai_dir.mkdir(parents=True)
    pdf_file = ai_dir / "Misha_AI.pdf"
    pdf_file.write_text("dummy pdf")

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    selected = select_resume("Looking for an AI engineer")
    assert selected is not None
    assert selected.endswith("resume_mlubich.pdf")

    selected_none = select_resume("marketing role")
    assert selected_none is None


def test_select_resume_no_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert select_resume("ai role") is None


@pytest.mark.parametrize(
    "job_text,variant",
    [
        ("looking for a fullstack engineer", "resume_mlubich_fullstack_ai"),
        ("devops infra role", "resume_mlubich_infra"),
        ("forward deployed engineer", "resume_mlubich_fde"),
        ("software engineer role", "resume_mlubich_swe"),
    ],
)
def test_select_resume_variants(tmp_path, monkeypatch, job_text, variant):
    resumes_dir = tmp_path / "dev/resumes/resumes"
    variant_dir = resumes_dir / variant
    variant_dir.mkdir(parents=True)
    (variant_dir / "resume.pdf").write_text("dummy")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert select_resume(job_text) is not None


def test_select_resume_falls_back_to_base_variant(tmp_path, monkeypatch):
    resumes_dir = tmp_path / "dev/resumes/resumes"
    base_dir = resumes_dir / "resume_mlubich"
    base_dir.mkdir(parents=True)
    (base_dir / "resume.pdf").write_text("dummy")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # "marketing role" matches no variant keywords, so falls back to the base dir
    assert select_resume("marketing role") is not None


# ---------------------------------------------------------------------------
# call_llm backend fallback
# ---------------------------------------------------------------------------


def _proc(returncode=0, stdout="", stderr=""):
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


def test_call_llm_uses_gemini_when_it_succeeds():
    good = _proc(0, '{"needs_reply": true, "interesting": true, "stakes": "low", '
                    '"intent": "other", "confidence": 0.9, "reply": "hi", "reason": "x", "learn": []}')
    with patch("imail.autodraft.subprocess.run", return_value=good) as mock_run:
        result = call_llm("prompt")
    assert result["needs_reply"] is True
    assert mock_run.call_count == 1
    assert mock_run.call_args_list[0].args[0][0] == "gemini"


def test_call_llm_falls_back_to_claude_when_gemini_fails():
    bad = _proc(1, "", "gemini quota exceeded")
    good = _proc(0, '```json\n{"needs_reply": false, "interesting": false, "stakes": "low", '
                    '"intent": "other", "confidence": 0.1, "reply": "", "reason": "x", "learn": []}\n```')
    with patch("imail.autodraft.subprocess.run", side_effect=[bad, good]) as mock_run:
        result = call_llm("prompt")
    assert result["needs_reply"] is False
    assert mock_run.call_count == 2
    assert mock_run.call_args_list[1].args[0][0] == "claude"


def test_call_llm_raises_when_all_backends_fail():
    bad = _proc(1, "", "down")
    with patch("imail.autodraft.subprocess.run", return_value=bad):
        with pytest.raises(Exception):
            call_llm("prompt")


def test_call_llm_raises_on_unparseable_output():
    garbage = _proc(0, "not json at all")
    with patch("imail.autodraft.subprocess.run", return_value=garbage):
        with pytest.raises(Exception):
            call_llm("prompt")


# ---------------------------------------------------------------------------
# process_inbox_autodraft pipeline
# ---------------------------------------------------------------------------

INBOX_ONE = [{"index": "1", "sender": "Nick <nick@davosig.com>", "subject": "quick question", "date": "x"}]

DEFAULT_DETAILS = {"body": "hey, are we still on for tomorrow?", "was_replied_to": False, "has_attachments": False}


def _llm_decision(**overrides):
    base = {
        "needs_reply": True,
        "interesting": True,
        "stakes": "low",
        "intent": "confirmation",
        "confidence": 0.96,
        "reply": "sounds good",
        "reason": "trivial confirmation",
        "learn": [],
    }
    base.update(overrides)
    return base


def _run_pipeline(tmp_path, monkeypatch, decision, known=True, details=None, dry_run=False):
    monkeypatch.setattr("imail.autodraft.SEEN_PATH", tmp_path / "seen.json")
    monkeypatch.setattr("imail.autodraft.LOG_PATH", tmp_path / "log.jsonl")
    with patch("imail.mail.list_messages", return_value=INBOX_ONE), \
         patch("imail.mail.get_message_details", return_value=details or DEFAULT_DETAILS), \
         patch("imail.mail.is_known_correspondent", return_value=known), \
         patch("imail.autodraft.call_llm", return_value=decision), \
         patch("imail.autodraft._brain_recall", return_value=""), \
         patch("imail.autodraft._brain_learn") as mock_learn, \
         patch("imail.autodraft.send_message") as mock_send, \
         patch("imail.autodraft.save_silent_draft") as mock_draft:
        results = process_inbox_autodraft(
            accounts=["michaelle.lubich@gmail.com"], dry_run=dry_run
        )
    return results, mock_send, mock_draft, mock_learn


def test_auto_send_for_known_low_stakes_high_confidence(tmp_path, monkeypatch):
    results, mock_send, mock_draft, _ = _run_pipeline(
        tmp_path, monkeypatch, _llm_decision(confidence=0.96), known=True
    )
    assert results[0]["status"] == "sent"
    mock_send.assert_called_once()
    mock_draft.assert_not_called()


def test_unknown_sender_at_high_confidence_is_only_drafted(tmp_path, monkeypatch):
    results, mock_send, mock_draft, _ = _run_pipeline(
        tmp_path, monkeypatch, _llm_decision(confidence=0.99), known=False
    )
    assert results[0]["status"] == "drafted"
    mock_send.assert_not_called()
    mock_draft.assert_called_once()


def test_confidence_below_threshold_is_drafted(tmp_path, monkeypatch):
    results, mock_send, mock_draft, _ = _run_pipeline(
        tmp_path, monkeypatch, _llm_decision(confidence=0.94), known=True
    )
    assert results[0]["status"] == "drafted"
    mock_send.assert_not_called()


def test_high_stakes_is_drafted_even_at_full_confidence(tmp_path, monkeypatch):
    results, mock_send, mock_draft, _ = _run_pipeline(
        tmp_path, monkeypatch, _llm_decision(confidence=0.99, stakes="high"), known=True
    )
    assert results[0]["status"] == "drafted"
    mock_send.assert_not_called()


def test_needs_reply_false_is_skipped_and_marked_seen(tmp_path, monkeypatch):
    results, mock_send, mock_draft, _ = _run_pipeline(
        tmp_path, monkeypatch, _llm_decision(needs_reply=False), known=True
    )
    assert results[0]["status"] == "skipped"
    mock_send.assert_not_called()
    mock_draft.assert_not_called()

    # second run: seen key must prevent reprocessing
    monkeypatch.setattr("imail.autodraft.SEEN_PATH", tmp_path / "seen.json")
    monkeypatch.setattr("imail.autodraft.LOG_PATH", tmp_path / "log.jsonl")
    with patch("imail.mail.list_messages", return_value=INBOX_ONE):
        second = process_inbox_autodraft(accounts=["michaelle.lubich@gmail.com"])
    assert second == []


def test_recruiter_intent_always_drafted_with_attachment(tmp_path, monkeypatch):
    with patch("imail.autodraft.select_resume", return_value="/tmp/resume_mlubich.pdf"):
        results, mock_send, mock_draft, _ = _run_pipeline(
            tmp_path,
            monkeypatch,
            _llm_decision(intent="recruiter", confidence=0.99, stakes="low"),
            known=True,
        )
    assert results[0]["status"] == "drafted"
    mock_send.assert_not_called()
    assert mock_draft.call_args.kwargs["attachments"] == ["/tmp/resume_mlubich.pdf"]


def test_llm_error_records_error_status_and_does_not_mark_seen(tmp_path, monkeypatch):
    monkeypatch.setattr("imail.autodraft.SEEN_PATH", tmp_path / "seen.json")
    monkeypatch.setattr("imail.autodraft.LOG_PATH", tmp_path / "log.jsonl")
    with patch("imail.mail.list_messages", return_value=INBOX_ONE), \
         patch("imail.mail.get_message_details", return_value=DEFAULT_DETAILS), \
         patch("imail.autodraft.call_llm", side_effect=RuntimeError("all backends failed")):
        first = process_inbox_autodraft(accounts=["michaelle.lubich@gmail.com"])
    assert first[0]["status"] == "error"

    with patch("imail.mail.list_messages", return_value=INBOX_ONE), \
         patch("imail.mail.get_message_details", return_value=DEFAULT_DETAILS), \
         patch("imail.autodraft.call_llm", side_effect=RuntimeError("all backends failed")):
        second = process_inbox_autodraft(accounts=["michaelle.lubich@gmail.com"])
    assert second[0]["status"] == "error"  # retried, not silently seen


def test_learn_facts_invoke_brain_learn(tmp_path, monkeypatch):
    decision = _llm_decision(learn=["nick prefers short replies"])
    results, mock_send, mock_draft, mock_learn = _run_pipeline(tmp_path, monkeypatch, decision, known=True)
    mock_learn.assert_called_once()
    assert "nick prefers short replies" in mock_learn.call_args.args[0]


def test_already_replied_to_is_skipped(tmp_path, monkeypatch):
    details = dict(DEFAULT_DETAILS, was_replied_to=True)
    results, mock_send, mock_draft, _ = _run_pipeline(
        tmp_path, monkeypatch, _llm_decision(), known=True, details=details
    )
    assert results[0]["status"] == "skipped"
    mock_send.assert_not_called()
    mock_draft.assert_not_called()


def test_dry_run_has_no_side_effects(tmp_path, monkeypatch):
    seen_path = tmp_path / "seen.json"
    log_path = tmp_path / "log.jsonl"
    results, mock_send, mock_draft, mock_learn = _run_pipeline(
        tmp_path,
        monkeypatch,
        _llm_decision(confidence=0.99, learn=["some fact"]),
        known=True,
        dry_run=True,
    )
    assert results[0]["status"] == "dry_run"
    mock_send.assert_not_called()
    mock_draft.assert_not_called()
    mock_learn.assert_not_called()
    assert not seen_path.exists()
    assert not log_path.exists()


# ---------------------------------------------------------------------------
# internals: subprocess boundary error handling, seen/log/accounts helpers
# ---------------------------------------------------------------------------


def test_call_llm_tolerates_timeout_and_oserror_then_raises():
    with patch(
        "imail.autodraft.subprocess.run",
        side_effect=[subprocess.TimeoutExpired(cmd="gemini", timeout=120), OSError("no claude binary")],
    ):
        with pytest.raises(Exception):
            call_llm("prompt")


def test_extract_json_tolerates_malformed_json_inside_braces():
    from imail.autodraft import _extract_json

    assert _extract_json("{this is not: valid json}") is None


def test_brain_recall_tolerates_failures():
    from imail.autodraft import _brain_recall

    with patch("imail.autodraft.subprocess.run", side_effect=OSError("no brain binary")):
        assert _brain_recall("query") == ""

    bad = _proc(1, "", "brain error")
    with patch("imail.autodraft.subprocess.run", return_value=bad):
        assert _brain_recall("query") == ""

    good = _proc(0, "some context")
    with patch("imail.autodraft.subprocess.run", return_value=good):
        assert _brain_recall("query") == "some context"


def test_brain_learn_invokes_subprocess_and_tolerates_failure():
    from imail.autodraft import _brain_learn

    with patch("imail.autodraft.subprocess.run") as mock_run:
        _brain_learn("some fact", title="t")
        assert mock_run.call_args.args[0][:2] == ["brain", "learn"]

    with patch("imail.autodraft.subprocess.run", side_effect=OSError("gone")):
        _brain_learn("some fact", title="t")  # must not raise


def test_load_seen_tolerates_corrupt_file(tmp_path):
    from imail.autodraft import _load_seen

    bad_file = tmp_path / "seen.json"
    bad_file.write_text("not json")
    assert _load_seen(bad_file) == set()

    dict_file = tmp_path / "seen2.json"
    dict_file.write_text('{"not": "a list"}')
    assert _load_seen(dict_file) == set()


def test_personal_accounts_uses_configured_emails(monkeypatch):
    from imail.autodraft import DEFAULT_PERSONAL, _personal_accounts

    monkeypatch.setattr(
        "imail.autodraft.load_accounts_config",
        lambda: {"walls": {"personal": {"emails": [DEFAULT_PERSONAL[0]]}}},
    )
    assert _personal_accounts() == [DEFAULT_PERSONAL[0]]


def test_pipeline_skips_blast_sender_before_touching_llm(tmp_path, monkeypatch):
    monkeypatch.setattr("imail.autodraft.SEEN_PATH", tmp_path / "seen.json")
    monkeypatch.setattr("imail.autodraft.LOG_PATH", tmp_path / "log.jsonl")
    blast_inbox = [
        {"index": "1", "sender": "spammer@kpg99.in", "subject": "OPENING FOR Engineer ::: REMOTE"},
    ]
    with patch("imail.mail.list_messages", return_value=blast_inbox), \
         patch("imail.autodraft.call_llm") as mock_llm:
        results = process_inbox_autodraft(accounts=["michaelle.lubich@gmail.com"])
    assert results == []
    mock_llm.assert_not_called()


def test_pipeline_records_error_when_message_details_fetch_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("imail.autodraft.SEEN_PATH", tmp_path / "seen.json")
    monkeypatch.setattr("imail.autodraft.LOG_PATH", tmp_path / "log.jsonl")
    with patch("imail.mail.list_messages", return_value=INBOX_ONE), \
         patch("imail.mail.get_message_details", side_effect=RuntimeError("osascript failed")):
        results = process_inbox_autodraft(accounts=["michaelle.lubich@gmail.com"])
    assert results[0]["status"] == "error"
    assert "osascript" in results[0]["error"]


def test_account_errors_are_recorded_not_swallowed():
    with patch("imail.mail.list_messages", side_effect=RuntimeError("Mail.app hung")):
        results = process_inbox_autodraft(accounts=["michaelle.lubich@gmail.com"])
    assert results
    assert results[0]["status"] == "error"
    assert "hung" in results[0]["error"]


def test_claude_backend_replaces_harness_system_prompt(monkeypatch):
    """Without --system-prompt the Claude Code harness wraps the call and haiku refuses bare JSON."""
    from imail import autodraft
    calls = []
    monkeypatch.setattr(autodraft, "_run_llm_command",
                        lambda cmd, input_text=None, timeout=120: calls.append(cmd) or (None if cmd[0] == "gemini" else '{"needs_reply": false}'))
    assert autodraft.call_llm("x") == {"needs_reply": False}
    claude = calls[1]
    assert "--system-prompt" in claude and claude[claude.index("--setting-sources") + 1] == ""
