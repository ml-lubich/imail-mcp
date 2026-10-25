"""Tests for imail.mail — osascript helpers with mocked subprocess."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from imail import mail


@pytest.mark.accounts_path
class TestAccountsJsonPath:
    def test_finds_repo_root_accounts_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        module_path = tmp_path / "src" / "imail" / "mail.py"
        module_path.parent.mkdir(parents=True)
        module_path.touch()
        expected = tmp_path / "accounts.json"
        expected.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(mail, "__file__", str(module_path))

        path = mail.accounts_json_path()

        assert path.name == "accounts.json"
        assert path == expected

    def test_raises_when_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        with patch.object(Path, "is_file", return_value=False):
            with pytest.raises(FileNotFoundError, match="accounts.json not found"):
                mail.accounts_json_path()

    def test_falls_back_to_home_config_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An installed (non-checkout) package finds accounts.json in ~/.config/imail."""
        home_cfg = tmp_path / "home" / ".config" / "imail" / "accounts.json"

        def fake_is_file(self: Path) -> bool:
            return self == home_cfg

        monkeypatch.setattr(Path, "is_file", fake_is_file)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        assert mail.accounts_json_path() == home_cfg


class TestLoadAccountsConfig:
    def test_loads_valid_json(self) -> None:
        config = mail.load_accounts_config()
        assert "walls" in config
        assert "aliases" in config


class TestRunAs:
    def test_returns_stdout_on_success(self) -> None:
        mock_result = MagicMock(returncode=0, stdout="hello\n", stderr="")
        with patch("imail.mail.subprocess.run", return_value=mock_result):
            assert mail.run_as("script") == "hello"

    def test_raises_on_nonzero_exit(self) -> None:
        mock_result = MagicMock(returncode=1, stdout="", stderr="Mail error")
        with patch("imail.mail.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="Mail error"):
                mail.run_as("script")

    def test_raises_with_stdout_fallback(self) -> None:
        mock_result = MagicMock(returncode=1, stdout="stdout err", stderr="")
        with patch("imail.mail.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="stdout err"):
                mail.run_as("script")


class TestEscapeApplescript:
    def test_escapes_quotes_and_backslashes(self) -> None:
        assert mail.escape_applescript('say "hi" \\ done') == 'say \\"hi\\" \\\\ done'


class TestDoctor:
    def test_returns_ok_message(self) -> None:
        with patch.object(mail, "run_as", return_value="Mail"):
            assert mail.doctor() == "ok: Mail.app reachable"


class TestListAccounts:
    def test_parses_tab_separated_rows(self) -> None:
        with patch.object(mail, "run_as", return_value="Google\tu@gmail.com\n"):
            rows = mail.list_accounts()
        assert rows == [("Google", "u@gmail.com")]

    def test_skips_lines_without_tab(self) -> None:
        with patch.object(mail, "run_as", return_value="orphan\nGoogle\tu@gmail.com\n"):
            rows = mail.list_accounts()
        assert rows == [("Google", "u@gmail.com")]


class TestFormatAccounts:
    def test_joins_accounts_as_tsv(self) -> None:
        with patch.object(mail, "list_accounts", return_value=[("A", "a@b.com")]):
            assert mail.format_accounts() == "A\ta@b.com"


class TestFormatWalls:
    def test_includes_walls_and_rules(self) -> None:
        text = mail.format_walls()
        assert "WORK:" in text
        assert "PERSONAL:" in text
        assert "primary Google:" in text
        assert "•" in text


class TestListMessages:
    def _mock_subprocess(self, stdout: str, returncode: int = 0):
        mock_result = MagicMock(returncode=returncode, stdout=stdout, stderr="")
        return patch("imail.mail.subprocess.run", return_value=mock_result)

    def test_parses_message_rows(self) -> None:
        line = "1\tMon Jan 1\talice@x.com\tHello"
        with self._mock_subprocess(f"{line}\n"):
            rows = mail.list_messages(account="Google", limit=5)
        assert rows == [
            {
                "index": "1",
                "date": "Mon Jan 1",
                "sender": "alice@x.com",
                "subject": "Hello",
            }
        ]

    def test_filters_by_query(self) -> None:
        line = "1\tMon Jan 1\tdelta@delta.com\tFlight receipt"
        with self._mock_subprocess(f"{line}\n") as mock_sub:
            rows = mail.list_messages(account="Google", limit=5, query="flight")
        assert len(rows) == 1
        assert rows[0]["subject"] == "Flight receipt"
        args, kwargs = mock_sub.call_args
        assert args[0] == ["osascript", "-", "Google", "INBOX", "5", "flight"]

    def test_raises_on_osascript_failure(self) -> None:
        with self._mock_subprocess("", returncode=1):
            with pytest.raises(RuntimeError):
                mail.list_messages()

    def test_skips_malformed_lines(self) -> None:
        with self._mock_subprocess("bad\nshort\ttab\n"):
            rows = mail.list_messages()
        assert len(rows) == 0

    def test_outbox_uses_global_mailbox_and_lists_rows(self) -> None:
        process = MagicMock(returncode=0, stdout="2\tNow\tme@example.com\tReferral\n", stderr="")
        with (
            patch("imail.mail.subprocess.run", return_value=process) as run,
            patch.object(mail, "_account_email", return_value="me@example.com"),
        ):
            rows = mail.list_messages(account="me@example.com", mailbox="Outbox")
        assert rows[0]["index"] == "2"
        assert rows[0]["subject"] == "Referral"
        assert "messages of outbox" in run.call_args.kwargs["input"]
        assert "globalIndex" in run.call_args.kwargs["input"]


class TestFormatListMessages:
    def test_formats_tsv_lines(self) -> None:
        rows = [{"index": "1", "date": "d", "sender": "s", "subject": "sub"}]
        with patch.object(mail, "list_messages", return_value=rows):
            text = mail.format_list_messages()
        assert text == "1\td\ts\tsub"


class TestSendMessage:
    def test_sends_without_cc(self) -> None:
        with patch.object(mail, "run_as", return_value="OK sent to a@b.com") as mock_run:
            result = mail.send_message(
                to="a@b.com",
                subject='Hi "there"',
                body="Body\\text",
                from_addr="",
            )
        assert "OK sent" in result
        script = mock_run.call_args[0][0]
        assert 'subject:"hi \\"there\\""' in script
        assert "make new cc recipient" not in script

    def test_sends_with_cc(self) -> None:
        with patch.object(mail, "run_as", return_value="OK") as mock_run:
            mail.send_message(
                to="a@b.com",
                subject="Subj",
                body="Body",
                from_addr="me@corp.com",
                cc="cc@corp.com",
            )
        script = mock_run.call_args[0][0]
        assert "make new cc recipient" in script
        assert "me@corp.com" in script

    def test_sends_with_markdown(self) -> None:
        with patch.object(mail, "run_as", return_value="OK") as mock_run:
            mail.send_message(
                to="a@b.com",
                subject="MD",
                body="# Header\n\n**Bold** text",
                from_addr="",
                is_markdown=True,
            )
        script = mock_run.call_args[0][0]
        assert "set rtfData to read rtfFile as «class RTF »" in script
        assert "content:rtfData" in script

    def test_sends_with_zip_attachments(self, tmp_path: Path) -> None:
        f1 = tmp_path / "doc1.txt"
        f2 = tmp_path / "doc2.txt"
        f1.write_text("Hello 1")
        f2.write_text("Hello 2")

        with patch.object(mail, "run_as", return_value="OK") as mock_run:
            mail.send_message(
                to="a@b.com",
                subject="Zipped",
                body="See zip",
                from_addr="",
                attachments=[str(f1), str(f2)],
                zip_attachments=True,
            )
        script = mock_run.call_args[0][0]
        assert ".zip" in script
        assert "doc1.txt" not in script  # individual files are bundled inside zip

    def test_sends_verified_when_outbox_empties(self) -> None:
        with patch.object(mail, "run_as", return_value="delivery_unknown: verify Sent") as mock_run:
            result = mail.send_message(
                to="a@b.com",
                subject="Test",
                body="Hello",
                from_addr="",
                verify_delivery=True,
            )
        assert "delivery_unknown" in result
        script = mock_run.call_args[0][0]
        assert "initialOut" not in script
        assert "count of messages of outbox" not in script

    def test_sends_warning_when_stuck_in_outbox(self) -> None:
        with patch.object(mail, "run_as", return_value="QUEUED in Outbox for a@b.com (pending send)") as mock_run:
            result = mail.send_message(
                to="a@b.com",
                subject="Test",
                body="Hello",
                from_addr="",
                verify_delivery=True,
            )
        assert "QUEUED in Outbox" in result

    def test_does_not_treat_outbox_count_change_as_delivery_verification(self) -> None:
        with patch.object(mail, "run_as", return_value="delivery_unknown") as mock_run:
            result = mail.send_message(
                to="a@b.com", subject="Test", body="Hello", from_addr="me@b.com",
                verify_delivery=True,
            )
        assert "delivery_unknown" in result
        assert "initialOut" not in mock_run.call_args[0][0]

    def test_network_failure_retries_only_after_exact_message_absent(self) -> None:
        sent = {"state": "SENT", "to": "a@b.com", "cc": "", "message_id": "m-1"}
        with (
            patch.object(mail, "run_as", side_effect=[RuntimeError("network"), "DISPATCHED"]) as dispatch,
            patch.object(mail, "_reconcile_outgoing", side_effect=[{"state": "ABSENT"}, {"state": "ABSENT"}, {"state": "ABSENT"}, sent]) as reconcile,
        ):
            result = mail.send_message("a@b.com", "Subject", "Body", "me@b.com", is_markdown=False)
        assert result == "OK sent to a@b.com (provider verified; Message-ID: m-1)"
        assert dispatch.call_count == 2
        assert reconcile.call_count == 4

    def test_network_failure_does_not_retry_when_exact_message_is_queued(self) -> None:
        queued = {"state": "OUTBOX", "to": "a@b.com"}
        with (
            patch.object(mail, "run_as", side_effect=RuntimeError("network")) as dispatch,
            patch.object(mail, "_reconcile_outgoing", return_value=queued),
        ):
            result = mail.send_message("a@b.com", "Subject", "Body", "me@b.com", is_markdown=False)
        assert "delivery_unknown" in result and "Outbox" in result
        dispatch.assert_called_once()

    def test_network_failure_does_not_retry_when_mail_state_is_unavailable(self) -> None:
        with (
            patch.object(mail, "run_as", side_effect=RuntimeError("network")) as dispatch,
            patch.object(mail, "_reconcile_outgoing", side_effect=RuntimeError("Mail unavailable")),
        ):
            result = mail.send_message("a@b.com", "Subject", "Body", "me@b.com", is_markdown=False)
        assert "delivery_unknown" in result
        dispatch.assert_called_once()

    def test_non_network_runtime_error_is_not_retried(self) -> None:
        with (
            patch.object(mail, "run_as", side_effect=RuntimeError("permission denied")) as dispatch,
            patch.object(mail, "_reconcile_outgoing") as reconcile,
        ):
            with pytest.raises(RuntimeError, match="permission denied"):
                mail.send_message("a@b.com", "Subject", "Body", "me@b.com", is_markdown=False)
        dispatch.assert_called_once()
        reconcile.assert_not_called()

    def test_retry_waits_for_delayed_exact_delivery_before_resending(self) -> None:
        sent = {"state": "SENT", "to": "a@b.com", "cc": "", "message_id": "late"}
        with (
            patch.object(mail, "run_as", side_effect=RuntimeError("network connection failed")) as dispatch,
            patch.object(mail, "_reconcile_outgoing", side_effect=[{"state": "ABSENT"}, {"state": "ABSENT"}, sent]) as reconcile,
            patch("imail.mail.time.sleep") as sleep,
        ):
            result = mail.send_message("a@b.com", "Subject", "Body", "me@b.com", is_markdown=False)
        assert result.endswith("Message-ID: late)")
        dispatch.assert_called_once()
        assert reconcile.call_count == 3
        assert sleep.call_count == 2

    def test_canonical_body_matches_markdown_rendered_mail(self) -> None:
        expected = mail._canonical_mail_body("hi **there**\n\nwelcome", is_markdown=True)
        rendered = mail._canonical_mail_body("<p>hi <strong>there</strong></p><p>welcome</p>", is_markdown=False)
        assert expected == rendered

    def test_reconciliation_uses_normalized_rendered_body(self) -> None:
        raw = "SENT\tprovider-id\ta@b.com\t\t\n---BODY---\n<p>hi <strong>there</strong></p><p>welcome</p>"
        with patch.object(mail, "run_as", return_value=raw):
            result = mail._reconcile_outgoing("me@b.com", "a@b.com", "", "Subject",
                                              "hi **there**\n\nwelcome", [], is_markdown=True)
        assert result["state"] == "SENT"

    def test_reconciliation_marks_different_body_ambiguous(self) -> None:
        raw = "SENT\tprovider-id\ta@b.com\t\t\n---BODY---\n<p>different message</p>"
        with patch.object(mail, "run_as", return_value=raw):
            result = mail._reconcile_outgoing("me@b.com", "a@b.com", "", "Subject",
                                              "expected message", [], is_markdown=False)
        assert result["state"] == "AMBIGUOUS"

    def test_reconciliation_rejects_unknown_provider_state(self) -> None:
        with patch.object(mail, "run_as", return_value="unexpected output"):
            with pytest.raises(RuntimeError, match="unrecognized reconciliation result"):
                mail._reconcile_outgoing("me@b.com", "a@b.com", "", "Subject", "Body", [], False)

    @pytest.mark.parametrize(
        ("provider_state", "expected"),
        [
            ({"state": "OUTBOX", "to": "a@b.com"}, "Outbox"),
            ({"state": "AMBIGUOUS"}, "delivery_unknown"),
            ({"state": "ABSENT"}, "not yet visible"),
        ],
    )
    def test_dispatch_reconciliation_does_not_claim_unverified_delivery(self, provider_state, expected) -> None:
        with (
            patch.object(mail, "run_as", return_value="DISPATCHED"),
            patch.object(mail, "_settled_reconcile", return_value=provider_state),
        ):
            result = mail.send_message("a@b.com", "Subject", "Body", "me@b.com", is_markdown=False)
        assert expected in result

    def test_transient_error_with_absence_and_zero_retry_reports_failure(self) -> None:
        with (
            patch.object(mail, "run_as", side_effect=RuntimeError("network disconnected")),
            patch.object(mail, "_settled_reconcile", return_value={"state": "ABSENT"}),
        ):
            result = mail.send_message("a@b.com", "Subject", "Body", "me@b.com", is_markdown=False, max_retries=0)
        assert result.startswith("send_failed:")


class TestMarkdownToHtml:
    def test_converts_headers_bold_italics_code(self) -> None:
        md = "# Title\n\nThis is **bold** and *italic* and `code`."
        html = mail.markdown_to_html(md)
        assert "<h1>Title</h1>" in html
        assert "bold" in html
        assert "<em>italic</em>" in html
        assert '"code"' in html or '&quot;code&quot;' in html

    def test_fallback_renderer_handles_paragraph_then_multiple_headings(self) -> None:
        with patch.dict(sys.modules, {"markdown_it": None}):
            html = mail.markdown_to_html("Paragraph\n# Heading\n## Subheading\n### Minor\nText")
        assert "Paragraph" in html and "<p>" in html
        assert "<h1>Heading</h1>" in html
        assert "<h2>Subheading</h2>" in html
        assert "<h3>Minor</h3>" in html

    def test_fallback_parser_without_markdown_it(self) -> None:
        with patch.dict("sys.modules", {"markdown_it": None}):
            md = "# Main Header\n## Sub Header\n### SubSub\n\n**Bold** text with *italic* and `code`."
            html = mail.markdown_to_html(md)
            assert "<h1>Main Header</h1>" in html
            assert "<h2>Sub Header</h2>" in html
            assert "<h3>SubSub</h3>" in html
            assert "Bold text" in html
            assert "<em>italic</em>" in html
            assert '"code"' in html or '&quot;code&quot;' in html


class TestZipAttachmentsError:
    def test_zip_attachments_raises_when_file_missing(self) -> None:
        with pytest.raises(FileNotFoundError, match="Attachment file not found"):
            mail.send_message(
                to="a@b.com",
                subject="Zip",
                body="Body",
                from_addr="",
                attachments=["/nonexistent/path/file.txt"],
                zip_attachments=True,
            )


class TestCreateEmlDraft:
    def test_creates_eml_file_and_opens(self, tmp_path: Path) -> None:
        f1 = tmp_path / "resume.pdf"
        f1.write_bytes(b"%PDF test")

        with patch("subprocess.run") as mock_sub:
            res = mail.create_eml_draft(
                to="recruiter@test.com",
                subject="Application",
                body="Body text",
                from_addr="sender@example.com",
                attachments=[str(f1)],
                is_markdown=True,
                zip_attachments=False,
                open_in_mail=True,
            )
        assert "OK opened draft in Mail.app" in res
        mock_sub.assert_called_once()
        cmd = mock_sub.call_args[0][0]
        assert cmd[:3] == ["open", "-a", "Mail"]


class TestHumanizeText:
    def test_strips_emojis_and_keeps_urls(self) -> None:
        raw = "Hi Michaelle 🚀, check https://github.com/blader/humanizer and email me@corp.com!"
        out = mail.humanize_text(raw, typo_rate=0.0)
        assert "🚀" not in out
        assert "https://github.com/blader/humanizer" in out
        assert "me@corp.com" in out
        assert "Hi Michaelle" in out

    def test_send_message_humanize_lowercases_subject(self) -> None:
        with patch.object(mail, "run_as", return_value="OK sent") as mock_run:
            mail.send_message(
                to="a@b.com",
                subject="Senior Full Stack Engineer Opportunity",
                body="Hi 🚀 Michaelle,\n\nI wanted to follow up.",
                from_addr="",
                humanize=True,
            )
        script = mock_run.call_args[0][0]
        assert 'subject:"senior full stack engineer opportunity"' in script.lower()
        assert "🚀" not in script

    def test_create_eml_draft_humanize(self, tmp_path: Path) -> None:
        with patch("subprocess.run"):
            res = mail.create_eml_draft(
                to="a@b.com",
                subject="Senior Full Stack Role",
                body="Hi 🚀 Michaelle,",
                from_addr="",
                humanize=True,
            )
        assert "OK opened draft" in res


class TestReadMessage:
    def test_parses_read_message_output(self) -> None:
        raw_output = (
            "123\tmid@example.com\treply@example.com\tsender@example.com\tTest Subject\t"
            "Mon Oct 4\ttrue\t2\tatt1.pdf, att2.png\tto@example.com\tcc@example.com\n---BODY---\nHello this is the full body text."
        )
        with patch.object(mail, "run_as", return_value=raw_output):
            result = mail.read_message(account="google", index=1)
        assert result["id"] == "123"
        assert result["message_id"] == "mid@example.com"
        assert result["reply_to"] == "reply@example.com"
        assert result["sender"] == "sender@example.com"
        assert result["subject"] == "Test Subject"
        assert result["was_replied_to"] is True
        assert result["attachment_count"] == 2
        assert result["attachments"] == ["att1.pdf", "att2.png"]
        assert result["to"] == ["to@example.com"]
        assert result["cc"] == ["cc@example.com"]
        assert result["body"] == "Hello this is the full body text."


class TestReadMessageById:
    def test_empty_message_id_is_rejected(self) -> None:
        with pytest.raises(RuntimeError, match="message ID is required"):
            mail.read_message_by_message_id("account@test", "")

    def test_parses_exact_message_id_with_to_cc_and_attachments(self) -> None:
        raw = (
            "42\t<stable@test>\treply@test\tSender <sender@test>\tRole\tToday\tfalse\t1\tresume.pdf\t"
            "recruiter@test\tjoe@test\n---BODY---\nHello"
        )
        with patch("imail.mail.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=raw, stderr="")) as run:
            result = mail.read_message_by_message_id("account@test", "<stable@test>")
        assert result["message_id"] == "<stable@test>"
        assert result["to"] == ["recruiter@test"]
        assert result["cc"] == ["joe@test"]
        assert result["attachments"] == ["resume.pdf"]
        assert result["body"] == "Hello"
        assert "<stable@test>" in run.call_args.args[0]

    def test_provider_error_fails_closed(self) -> None:
        with patch("imail.mail.subprocess.run", return_value=SimpleNamespace(returncode=1, stdout="", stderr="Mail unavailable")):
            with pytest.raises(RuntimeError, match="Mail unavailable"):
                mail.read_message_by_message_id("account@test", "<stable@test>")

    def test_malformed_provider_output_fails_closed(self) -> None:
        with patch("imail.mail.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="unexpected", stderr="")):
            with pytest.raises(RuntimeError, match="unexpected output"):
                mail.read_message_by_message_id("account@test", "<stable@test>")

    def test_read_message_missing_body_marker(self) -> None:
        with patch.object(mail, "run_as", return_value="invalid format"):
            with pytest.raises(RuntimeError, match="unexpected output from Mail.app"):
                mail.read_message(account="google", index=1)

    def test_outbox_read_uses_global_mailbox(self) -> None:
        raw = "1\tmid\treply@x\tsender@x\tSubject\tNow\tfalse\t0\t\tto@x\tcc@x\n---BODY---\nBody"
        with (
            patch.object(mail, "run_as", return_value=raw) as run,
            patch.object(mail, "_account_email", return_value="sender@x"),
        ):
            result = mail.read_message(account="google", mailbox="Outbox", index=1)
        assert result["to"] == ["to@x"]
        assert result["cc"] == ["cc@x"]
        assert "set box to outbox" in run.call_args[0][0]

    def test_outbox_read_enforces_requested_account(self) -> None:
        raw = "1\tmid\treply@x\tother@example.com\tSubject\tNow\tfalse\t0\t\tto@x\t\n---BODY---\nBody"
        with (
            patch.object(mail, "run_as", return_value=raw),
            patch.object(mail, "_account_email", return_value="me@example.com"),
        ):
            with pytest.raises(RuntimeError, match="does not belong to requested account"):
                mail.read_message(account="account-name", mailbox="Outbox", index=1)


class TestReplyMessage:
    def test_reply_message_sends(self) -> None:
        mock_msg = {
            "id": "1",
            "message_id": "mid@test",
            "reply_to": "dest@test.com",
            "sender": "dest@test.com",
            "subject": "Original Subject",
            "date": "Now",
            "was_replied_to": False,
            "attachment_count": 0,
            "attachments": [],
            "body": "Original body",
        }
        with (
            patch.object(mail, "read_message", return_value=mock_msg),
            patch.object(mail, "read_message_by_message_id", return_value=mock_msg),
            patch.object(mail, "send_message", return_value="OK sent to dest@test.com (verified)") as mock_send,
        ):
            res = mail.reply_message(
                account="google",
                index=1,
                body="Replying back",
                attachments=["/tmp/test.pdf"],
                expected_recipient="dest@test.com",
                expected_sender="dest@test.com",
            )
        assert "OK sent" in res
        mock_send.assert_called_once_with(
            to="dest@test.com",
            subject="Re: Original Subject",
            body="Replying back",
            from_addr="google",
            cc="",
            attachments=["/tmp/test.pdf"],
            is_markdown=True,
            zip_attachments=False,
            humanize=False,
            max_retries=1,
        )

    def test_reply_fails_closed_when_message_id_changed_since_list(self) -> None:
        listed = {"message_id": "wanted-id", "reply_to": "right@test.com", "sender": "right@test.com",
                  "subject": "Role", "was_replied_to": False}
        resolved = {**listed, "message_id": "new-top-message", "reply_to": "wrong@test.com",
                    "sender": "wrong@test.com"}
        with (
            patch.object(mail, "read_message", return_value=listed),
            patch.object(mail, "read_message_by_message_id", return_value=resolved),
            patch.object(mail, "send_message") as send,
        ):
            with pytest.raises(RuntimeError, match="message changed"):
                mail.reply_message(account="google", index=1, body="hello",
                                   expected_sender="right@test.com", expected_recipient="right@test.com")
        send.assert_not_called()

    def test_reply_requires_explicit_recipient_guard(self) -> None:
        mock_msg = {"message_id": "id", "reply_to": "dest@test.com", "sender": "dest@test.com",
                    "subject": "Role", "was_replied_to": False}
        with (
            patch.object(mail, "read_message", return_value=mock_msg),
            patch.object(mail, "read_message_by_message_id", return_value=mock_msg),
        ):
            with pytest.raises(RuntimeError, match="expected recipient"):
                mail.reply_message(account="google", index=1, body="hello")

    def test_reply_message_opens_draft(self) -> None:
        mock_msg = {
            "id": "1",
            "message_id": "mid@test",
            "reply_to": "dest@test.com",
            "sender": "dest@test.com",
            "subject": "Re: Already Prefixed",
            "date": "Now",
            "was_replied_to": False,
            "attachment_count": 0,
            "attachments": [],
            "body": "Original body",
        }
        with (
            patch.object(mail, "read_message", return_value=mock_msg),
            patch.object(mail, "read_message_by_message_id", return_value=mock_msg),
            patch.object(mail, "create_eml_draft", return_value="OK opened draft") as mock_draft,
        ):
            res = mail.reply_message(
                account="google",
                index=1,
                body="Replying back",
                open_draft=True,
            )
        assert "OK opened draft" in res
        mock_draft.assert_called_once_with(
            to="dest@test.com",
            subject="Re: Already Prefixed",
            body="Replying back",
            from_addr="google",
            attachments=None,
            is_markdown=True,
            zip_attachments=False,
            open_in_mail=True,
            humanize=False,
        )

    def test_reply_message_cannot_determine_recipient(self) -> None:
        mock_msg = {
            "id": "1",
            "message_id": "",
            "reply_to": "",
            "sender": "",
            "subject": "Subj",
            "date": "",
            "was_replied_to": False,
            "attachment_count": 0,
            "attachments": [],
            "body": "",
        }
        with patch.object(mail, "read_message", return_value=mock_msg):
            with pytest.raises(RuntimeError, match="no stable Message-ID"):
                mail.reply_message(account="google", index=1, body="test")


