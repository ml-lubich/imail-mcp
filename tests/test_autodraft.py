"""Tests for imail autodraft engine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from imail.autodraft import (
    INTENT_CONFIRMATION,
    INTENT_DIRECT_INQUIRY,
    INTENT_RECRUITER,
    INTENT_SKIP,
    classify_intent,
    generate_draft_response,
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

    # Fallback when no matching variant exists
    selected_none = select_resume("marketing role")
    assert selected_none is None


def test_select_resume_no_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert select_resume("ai role") is None


def test_generate_draft_response_recruiter_with_resume(monkeypatch):
    monkeypatch.setattr("imail.autodraft.select_resume", lambda x: "/tmp/resume_mlubich.pdf")
    decision = generate_draft_response(
        account="michaelle.lubich@gmail.com",
        sender="Griffen Rude <grude@tundratechnical.com>",
        subject="Job with Meta",
    )
    assert decision is not None
    assert decision.recipient == "grude@tundratechnical.com"
    assert "Re: Job with Meta" in decision.subject
    assert "what made you reach out to me" in decision.body
    assert decision.attachments == ["/tmp/resume_mlubich.pdf"]
    assert not decision.auto_send


def test_generate_draft_response_recruiter_no_resume(monkeypatch):
    monkeypatch.setattr("imail.autodraft.select_resume", lambda x: None)
    decision = generate_draft_response(
        account="michaelle.lubich@gmail.com",
        sender="Griffen Rude <grude@tundratechnical.com>",
        subject="Job with Meta",
    )
    assert decision is not None
    assert decision.attachments == []


def test_generate_draft_response_confirmation():
    decision = generate_draft_response(
        account="michaelle.lubich@gmail.com",
        sender="Client <client@example.com>",
        subject="Re: Meeting confirmation",
        snippet="sounds good let us meet",
    )
    assert decision is not None
    assert "sounds good" in decision.body


def test_generate_draft_response_inquiry():
    decision = generate_draft_response(
        account="michaelle.lubich@gmail.com",
        sender="Partner <partner@example.com>",
        subject="Update on project?",
    )
    assert decision is not None
    assert "taking a look at this now" in decision.body


def test_generate_draft_response_skip():
    decision = generate_draft_response(
        account="michaelle.lubich@gmail.com",
        sender="noreply@substack.com",
        subject="New post from Substack",
    )
    assert decision is None


@patch("imail.mail.list_messages")
@patch("imail.autodraft.save_silent_draft")
def test_process_inbox_autodraft_dry_run(mock_save, mock_list, tmp_path, monkeypatch):
    monkeypatch.setattr("imail.autodraft.SEEN_PATH", tmp_path / "seen.json")
    mock_list.return_value = [
        {"sender": "Griffen Rude <grude@tundratechnical.com>", "subject": "Job with Meta"},
        {"sender": "newsletter@domain.com", "subject": "Daily digest"},
    ]

    results = process_inbox_autodraft(
        accounts=["michaelle.lubich@gmail.com"],
        dry_run=True,
    )
    assert len(results) == 1
    assert results[0]["status"] == "dry_run"
    assert results[0]["recipient"] == "grude@tundratechnical.com"
    mock_save.assert_not_called()


@patch("imail.mail.list_messages")
@patch("imail.autodraft.save_silent_draft")
def test_process_inbox_autodraft_real(mock_save, mock_list, tmp_path, monkeypatch):
    monkeypatch.setattr("imail.autodraft.SEEN_PATH", tmp_path / "seen.json")
    mock_list.return_value = [
        {"sender": "Griffen Rude <grude@tundratechnical.com>", "subject": "Job with Meta"},
    ]

    results = process_inbox_autodraft(
        accounts=["michaelle.lubich@gmail.com"],
        dry_run=False,
    )
    assert len(results) == 1
    assert results[0]["status"] == "drafted"
    mock_save.assert_called_once()


@patch("imail.mail.list_messages")
@patch("imail.autodraft.send_message")
def test_process_inbox_autodraft_auto_send(mock_send, mock_list, tmp_path, monkeypatch):
    monkeypatch.setattr("imail.autodraft.SEEN_PATH", tmp_path / "seen.json")
    mock_list.return_value = [
        {"sender": "Griffen Rude <grude@tundratechnical.com>", "subject": "Job with Meta"},
    ]
    with patch("imail.autodraft.generate_draft_response") as mock_gen:
        from imail.autodraft import DraftDecision
        mock_gen.return_value = DraftDecision(
            account="michaelle.lubich@gmail.com",
            recipient="grude@tundratechnical.com",
            subject="Re: Job with Meta",
            body="Sure thing",
            attachments=[],
            intent="confirmation",
            auto_send=True,
            confidence=0.99,
        )
        results = process_inbox_autodraft(
            accounts=["michaelle.lubich@gmail.com"],
            dry_run=False,
        )
        assert len(results) == 1
        assert results[0]["status"] == "sent"
        mock_send.assert_called_once()


def test_classify_intent_skips_generic_blast_recruiters():
    from imail.autodraft import classify_intent, INTENT_SKIP, INTENT_RECRUITER

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
        "Kaustubh <Kaustubh.Kashyap@rulesiq.com>",
        "URGENT || Remote Job Opportunity || Monitoring/Observability Tool Developer-",
    ) == INTENT_SKIP
    assert classify_intent(
        "Griffen Rude <grude@tundratechnical.com>",
        "Job with Meta",
    ) == INTENT_RECRUITER


def test_draft_voice_is_lowercase_plain_text_no_analogies(monkeypatch):
    monkeypatch.setattr("imail.autodraft.select_resume", lambda x: "/tmp/resume_mlubich.pdf")
    decision = generate_draft_response(
        account="michaelle.lubich@gmail.com",
        sender="Griffen Rude <grude@tundratechnical.com>",
        subject="Job with Meta",
    )
    assert decision is not None
    body = decision.body
    assert "**" not in body and "`" not in body and "#" not in body
    assert "—" not in body and "--" not in body
    assert "like a" not in body.lower()
    assert body == body.lower()
    assert "what made you reach out" in body
    assert body.strip().endswith("misha")


def test_known_low_stakes_followup_may_auto_send():
    decision = generate_draft_response(
        account="michaelle.lubich@gmail.com",
        sender="Nick <nick@davosig.com>",
        subject="sounds good, see you tomorrow",
        known_correspondent=True,
    )
    assert decision is not None
    assert decision.auto_send is True
    assert decision.confidence >= 0.95
    assert decision.body == decision.body.lower()


def test_unknown_confirmation_stays_a_draft():
    decision = generate_draft_response(
        account="michaelle.lubich@gmail.com",
        sender="Stranger <newperson@example.com>",
        subject="sounds good, see you tomorrow",
        known_correspondent=False,
    )
    assert decision is not None
    assert decision.auto_send is False


def test_already_seen_thread_is_not_drafted_twice(tmp_path, monkeypatch):
    from imail import autodraft

    monkeypatch.setattr(autodraft, "SEEN_PATH", tmp_path / "seen.json")
    monkeypatch.setattr("imail.autodraft.select_resume", lambda x: None)

    inbox = [{"sender": "Griffen Rude <grude@tundratechnical.com>", "subject": "Job with Meta"}]
    with patch("imail.mail.list_messages", return_value=inbox), \
         patch("imail.autodraft.save_silent_draft") as mock_save:
        first = process_inbox_autodraft(accounts=["michaelle.lubich@gmail.com"])
        second = process_inbox_autodraft(accounts=["michaelle.lubich@gmail.com"])
    assert len(first) == 1 and first[0]["status"] == "drafted"
    assert second == []
    assert mock_save.call_count == 1


def test_account_errors_are_recorded_not_swallowed():
    with patch("imail.mail.list_messages", side_effect=RuntimeError("Mail.app hung")):
        results = process_inbox_autodraft(accounts=["michaelle.lubich@gmail.com"])
    assert results
    assert results[0]["status"] == "error"
    assert "hung" in results[0]["error"]
