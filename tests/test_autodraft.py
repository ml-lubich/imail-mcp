"""Tests for imail autodraft engine."""

from __future__ import annotations
import json

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


@pytest.fixture(autouse=True)
def _no_real_openai(monkeypatch):
    """Tests never hit the network; individual tests opt in by patching _openai_complete."""
    monkeypatch.setattr("imail.autodraft._openai_complete", lambda prompt: None)


def test_call_llm_uses_openai_first(monkeypatch):
    monkeypatch.setattr("imail.autodraft._openai_complete", lambda prompt: '{"needs_reply": true}')
    with patch("imail.autodraft.subprocess.run") as mock_run:
        assert call_llm("prompt") == {"needs_reply": True}
    mock_run.assert_not_called()


def test_call_llm_falls_back_to_claude_when_openai_fails():
    good = _proc(0, '```json\n{"needs_reply": false}\n```')
    with patch("imail.autodraft.subprocess.run", return_value=good) as mock_run:
        assert call_llm("prompt") == {"needs_reply": False}
    assert mock_run.call_args_list[0].args[0][0] == "claude"


def test_openai_complete_posts_cheap_model_with_keychain_key(monkeypatch):
    from imail import autodraft
    monkeypatch.undo()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(autodraft, "_openai_key", lambda: "sk-test")
    sent = {}
    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"choices":[{"message":{"content":"{\\"needs_reply\\": true}"}}]}'
    def fake_urlopen(req, timeout):
        sent["auth"] = req.get_header("Authorization"); sent["body"] = json.loads(req.data)
        return Resp()
    monkeypatch.setattr(autodraft.urllib.request, "urlopen", fake_urlopen)
    assert autodraft._openai_complete("hello") == '{"needs_reply": true}'
    assert sent["auth"] == "Bearer sk-test"
    assert sent["body"]["model"] == autodraft.OPENAI_MODEL == "gpt-5-nano"
    assert sent["body"]["reasoning_effort"] == "minimal"


def test_openai_complete_returns_none_without_key_or_on_error(monkeypatch):
    from imail import autodraft
    monkeypatch.undo()
    monkeypatch.setattr(autodraft, "_openai_key", lambda: "")
    assert autodraft._openai_complete("x") is None
    monkeypatch.setattr(autodraft, "_openai_key", lambda: "sk-test")
    def boom(req, timeout): raise OSError("network down")
    monkeypatch.setattr(autodraft.urllib.request, "urlopen", boom)
    assert autodraft._openai_complete("x") is None


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
        side_effect=OSError("no claude binary"),
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
                        lambda cmd, input_text=None, timeout=120: calls.append(cmd) or '{"needs_reply": false}')
    assert autodraft.call_llm("x") == {"needs_reply": False}
    claude = calls[0]
    assert "--system-prompt" in claude and claude[claude.index("--setting-sources") + 1] == ""


# --- review findings: the LLM decision is untrusted, fail closed ------------

@pytest.mark.parametrize("bad", [
    {"needs_reply": "false"},          # bool("false") is True
    {"interesting": "true"},
    {"confidence": "0.99"},
    {"confidence": "n/a"},
    {"confidence": True},
    {"stakes": "LOW"},
    {"reply": 5},
])
def test_malformed_decision_is_error_not_sent_and_not_seen(tmp_path, monkeypatch, bad):
    results, mock_send, mock_draft, _ = _run_pipeline(tmp_path, monkeypatch, _llm_decision(**bad), known=True)
    assert results[0]["status"] == "error"
    mock_send.assert_not_called()
    mock_draft.assert_not_called()
    assert not (tmp_path / "seen.json").exists()


def test_display_name_spoof_uses_real_address(tmp_path, monkeypatch):
    spoof = [{"index": "1", "date": "d", "sender": '"misha.friend@gmail.com" <attacker@evil.io>', "subject": "hi"}]
    monkeypatch.setattr("imail.autodraft.SEEN_PATH", tmp_path / "seen.json")
    monkeypatch.setattr("imail.autodraft.LOG_PATH", tmp_path / "log.jsonl")
    with patch("imail.mail.list_messages", return_value=spoof), \
         patch("imail.mail.get_message_details", return_value=DEFAULT_DETAILS), \
         patch("imail.mail.is_known_correspondent", return_value=False) as known, \
         patch("imail.autodraft.call_llm", return_value=_llm_decision()), \
         patch("imail.autodraft._brain_recall", return_value=""), \
         patch("imail.autodraft._brain_learn"), \
         patch("imail.autodraft.send_message"), \
         patch("imail.autodraft.save_silent_draft") as draft:
        process_inbox_autodraft(accounts=["michaelle.lubich@gmail.com"])
    known.assert_called_once_with("attacker@evil.io")
    assert draft.call_args.kwargs["to"] == "attacker@evil.io"


def test_learn_facts_that_look_like_flags_are_dropped(tmp_path, monkeypatch):
    decision = _llm_decision(learn=["--push", 7, "nick prefers short replies"])
    _, _, _, mock_learn = _run_pipeline(tmp_path, monkeypatch, decision, known=True)
    assert [c.args[0] for c in mock_learn.call_args_list] == ["nick prefers short replies"]


# ---------------------------------------------------------------------------
# auto_send_allowed (extracted pure gate)
# ---------------------------------------------------------------------------


def test_auto_send_allowed_true_when_all_conditions_met():
    from imail.autodraft import auto_send_allowed

    decision = {"confidence": 0.96, "stakes": "low", "intent": "confirmation"}
    assert auto_send_allowed(decision, known=True, has_attachments=False, reply_body="ok") is True


@pytest.mark.parametrize(
    "overrides,known,has_attachments,reply_body",
    [
        ({"confidence": 0.5}, True, False, "ok"),  # confidence too low
        ({"stakes": "high"}, True, False, "ok"),  # high stakes
        ({}, False, False, "ok"),  # unknown correspondent
        ({}, True, True, "ok"),  # incoming attachments
        ({"intent": "recruiter"}, True, False, "ok"),  # recruiter
        ({}, True, False, "x" * 500),  # reply too long
    ],
)
def test_auto_send_allowed_false_when_any_gate_fails(overrides, known, has_attachments, reply_body):
    from imail.autodraft import auto_send_allowed

    decision = {"confidence": 0.99, "stakes": "low", "intent": "confirmation", **overrides}
    assert auto_send_allowed(decision, known, has_attachments, reply_body) is False


# ---------------------------------------------------------------------------
# autodraft-log
# ---------------------------------------------------------------------------


def test_read_recent_log_missing_file(tmp_path):
    from imail.autodraft import read_recent_log

    assert read_recent_log(20, tmp_path / "missing.jsonl") == []


def test_read_recent_log_tolerates_corrupt_lines_and_limits_n(tmp_path):
    from imail.autodraft import read_recent_log

    log = tmp_path / "log.jsonl"
    lines = [json.dumps({"i": i}) for i in range(5)]
    lines.insert(2, "not json")
    log.write_text("\n".join(lines) + "\n")
    entries = read_recent_log(3, log)
    assert len(entries) == 3
    assert [e["i"] for e in entries] == [2, 3, 4]


def test_format_recent_log_empty(tmp_path):
    from imail.autodraft import format_recent_log

    assert format_recent_log(20, tmp_path / "missing.jsonl") == "No autodraft log entries yet."


def test_format_recent_log_renders_fields(tmp_path):
    from imail.autodraft import format_recent_log

    log = tmp_path / "log.jsonl"
    entry = {
        "timestamp": "2026-09-24T00:00:00+00:00",
        "account": "michaelle.lubich@gmail.com",
        "recipient": "friend@example.com",
        "subject": "Re: lunch",
        "status": "sent",
        "confidence": 0.97,
        "stakes": "low",
        "reason": "trivial confirmation",
    }
    log.write_text(json.dumps(entry) + "\n")
    output = format_recent_log(20, log)
    assert "SENT" in output
    assert "friend@example.com" in output
    assert "trivial confirmation" in output


def test_lupfr_is_never_autodrafted(monkeypatch):
    from imail import autodraft
    monkeypatch.setattr(autodraft, "load_accounts_config",
                        lambda: {"walls": {"personal": {"emails": ["michaelle.lubich@gmail.com", "misha@lupfr.com"]}}})
    assert "misha@lupfr.com" not in autodraft._personal_accounts()
    assert "misha@lupfr.com" not in autodraft.DEFAULT_PERSONAL
