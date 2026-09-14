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
    assert "What made you reach out to me" in decision.body
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
    assert "Sounds good" in decision.body


def test_generate_draft_response_inquiry():
    decision = generate_draft_response(
        account="michaelle.lubich@gmail.com",
        sender="Partner <partner@example.com>",
        subject="Update on project?",
    )
    assert decision is not None
    assert "Taking a look at this now" in decision.body


def test_generate_draft_response_skip():
    decision = generate_draft_response(
        account="michaelle.lubich@gmail.com",
        sender="noreply@substack.com",
        subject="New post from Substack",
    )
    assert decision is None


@patch("imail.mail.list_messages")
@patch("imail.autodraft.save_silent_draft")
def test_process_inbox_autodraft_dry_run(mock_save, mock_list):
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
def test_process_inbox_autodraft_real(mock_save, mock_list):
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
def test_process_inbox_autodraft_auto_send(mock_send, mock_list):
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
