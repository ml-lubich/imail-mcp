"""Tests for imail.mail — osascript helpers with mocked subprocess."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from imail import mail


class TestAccountsJsonPath:
    def test_finds_repo_root_accounts_json(self) -> None:
        path = mail.accounts_json_path()
        assert path.name == "accounts.json"
        assert path.is_file()

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
        with patch.object(mail, "run_as", return_value="OK sent to a@b.com (verified)") as mock_run:
            result = mail.send_message(
                to="a@b.com",
                subject="Test",
                body="Hello",
                from_addr="",
                verify_delivery=True,
            )
        assert "verified" in result
        script = mock_run.call_args[0][0]
        assert "outbox" in script

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


class TestMarkdownToHtml:
    def test_converts_headers_bold_italics_code(self) -> None:
        md = "# Title\n\nThis is **bold** and *italic* and `code`."
        html = mail.markdown_to_html(md)
        assert "<h1>Title</h1>" in html
        assert "bold" in html
        assert "<em>italic</em>" in html
        assert '"code"' in html or '&quot;code&quot;' in html

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
                from_addr="misha@lupfr.com",
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
            "Mon Oct 4\ttrue\t2\tatt1.pdf, att2.png\n---BODY---\nHello this is the full body text."
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
        assert result["body"] == "Hello this is the full body text."

    def test_read_message_missing_body_marker(self) -> None:
        with patch.object(mail, "run_as", return_value="invalid format"):
            with pytest.raises(RuntimeError, match="unexpected output from Mail.app"):
                mail.read_message(account="google", index=1)


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
            patch.object(mail, "send_message", return_value="OK sent to dest@test.com (verified)") as mock_send,
        ):
            res = mail.reply_message(
                account="google",
                index=1,
                body="Replying back",
                attachments=["/tmp/test.pdf"],
            )
        assert "OK sent" in res
        mock_send.assert_called_once_with(
            to="dest@test.com",
            subject="Re: Original Subject",
            body="Replying back",
            from_addr="google",
            attachments=["/tmp/test.pdf"],
            is_markdown=True,
            zip_attachments=False,
            humanize=False,
        )

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
            with pytest.raises(RuntimeError, match="Could not determine recipient"):
                mail.reply_message(account="google", index=1, body="test")


