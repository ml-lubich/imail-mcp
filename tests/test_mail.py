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
        assert 'subject:"Hi \\"there\\""' in script
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
