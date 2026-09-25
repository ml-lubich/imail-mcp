"""CLI command tests with mocked mail/organize backends."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from imail.cli import app

runner = CliRunner()


class TestDoctorCmd:
    def test_doctor_success(self) -> None:
        with (
            patch("imail.cli.mail.doctor", return_value="ok: Mail.app reachable"),
            patch("imail.cli.mail.format_accounts", return_value="Google\tu@gmail.com"),
        ):
            result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "ok: Mail.app reachable" in result.output

    def test_doctor_failure(self) -> None:
        with patch("imail.cli.mail.doctor", side_effect=RuntimeError("denied")):
            result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 1
        assert "FAIL: denied" in result.output


class TestAccountsCmd:
    def test_accounts_success(self) -> None:
        with patch("imail.cli.mail.format_accounts", return_value="A\ta@b.com"):
            result = runner.invoke(app, ["accounts"])
        assert result.exit_code == 0
        assert "A\ta@b.com" in result.output

    def test_accounts_failure(self) -> None:
        with patch(
            "imail.cli.mail.format_accounts",
            side_effect=RuntimeError("no mail"),
        ):
            result = runner.invoke(app, ["accounts"])
        assert result.exit_code == 1


class TestWallsCmd:
    def test_walls_success(self) -> None:
        with patch("imail.cli.mail.format_walls", return_value="WORK: Exchange"):
            result = runner.invoke(app, ["walls"])
        assert result.exit_code == 0
        assert "WORK:" in result.output

    def test_walls_missing_config(self) -> None:
        with patch(
            "imail.cli.mail.format_walls",
            side_effect=FileNotFoundError("accounts.json not found"),
        ):
            result = runner.invoke(app, ["walls"])
        assert result.exit_code == 1


class TestListCmd:
    def test_list_plain(self) -> None:
        with patch(
            "imail.cli.mail.format_list_messages",
            return_value="1\td\ts\tsub",
        ):
            result = runner.invoke(app, ["list", "--limit", "5"])
        assert result.exit_code == 0
        assert "1\td\ts\tsub" in result.output

    def test_list_json(self) -> None:
        rows = [{"index": "1", "date": "d", "sender": "s", "subject": "sub"}]
        with patch("imail.cli.mail.list_messages", return_value=rows):
            result = runner.invoke(app, ["list", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == rows

    def test_list_failure(self) -> None:
        with patch(
            "imail.cli.mail.format_list_messages",
            side_effect=RuntimeError("list fail"),
        ):
            result = runner.invoke(app, ["list"])
        assert result.exit_code == 1


class TestOrganizeCmd:
    def test_organize_exits_with_code(self) -> None:
        with patch("imail.cli.organize.organize_inboxes", return_value=0):
            result = runner.invoke(app, ["organize", "--account", "google"])
        assert result.exit_code == 0

    def test_organize_failure_code(self) -> None:
        with patch("imail.cli.organize.organize_inboxes", return_value=2):
            result = runner.invoke(app, ["organize", "-a", "missing"])
        assert result.exit_code == 2


class TestSendCmd:
    def test_send_success(self) -> None:
        with patch("imail.cli.mail.send_message", return_value="OK sent"):
            result = runner.invoke(
                app,
                [
                    "send",
                    "--from",
                    "me@corp.com",
                    "--to",
                    "a@b.com",
                    "--subject",
                    "Hi",
                    "--body",
                    "Hello",
                ],
            )
        assert result.exit_code == 0
        assert "OK sent" in result.output

    def test_send_with_body_file(self, tmp_path: Path) -> None:
        body_file = tmp_path / "email.md"
        body_file.write_text("# Hello from file")

        with patch("imail.cli.mail.send_message", return_value="OK sent") as mock_send:
            result = runner.invoke(
                app,
                [
                    "send",
                    "--from",
                    "me@corp.com",
                    "--to",
                    "a@b.com",
                    "--subject",
                    "Hi",
                    "--body-file",
                    str(body_file),
                ],
            )
        assert result.exit_code == 0
        mock_send.assert_called_once()
        assert mock_send.call_args[1]["body"] == "# Hello from file"
        assert mock_send.call_args[1]["is_markdown"] is True  # auto-detected .md file

    def test_send_with_body_as_existing_file(self, tmp_path: Path) -> None:
        body_file = tmp_path / "note.txt"
        body_file.write_text("Text from file path")

        with patch("imail.cli.mail.send_message", return_value="OK sent") as mock_send:
            result = runner.invoke(
                app,
                [
                    "send",
                    "--from",
                    "me@corp.com",
                    "--to",
                    "a@b.com",
                    "--subject",
                    "Hi",
                    "--body",
                    str(body_file),
                ],
            )
        assert result.exit_code == 0
        assert mock_send.call_args[1]["body"] == "Text from file path"

    def test_send_with_markdown_and_zip_flags(self) -> None:
        with patch("imail.cli.mail.send_message", return_value="OK sent") as mock_send:
            result = runner.invoke(
                app,
                [
                    "send",
                    "--from",
                    "me@corp.com",
                    "--to",
                    "a@b.com",
                    "--subject",
                    "Hi",
                    "--body",
                    "Hello",
                    "-m",
                    "--zip",
                ],
            )
        assert result.exit_code == 0
        assert mock_send.call_args[1]["is_markdown"] is True
        assert mock_send.call_args[1]["zip_attachments"] is True

    def test_send_missing_body_file(self) -> None:
        result = runner.invoke(
            app,
            [
                "send",
                "--from",
                "me@corp.com",
                "--to",
                "a@b.com",
                "--subject",
                "Hi",
                "--body-file",
                "/nonexistent/file.md",
            ],
        )
        assert result.exit_code == 1
        assert "Body file not found" in result.output

    def test_send_missing_body(self) -> None:
        result = runner.invoke(
            app,
            [
                "send",
                "--from",
                "me@corp.com",
                "--to",
                "a@b.com",
                "--subject",
                "Hi",
            ],
        )
        assert result.exit_code == 1
        assert "Email body or body file is required" in result.output

    def test_send_humanize_flag(self) -> None:
        with patch("imail.cli.mail.send_message", return_value="OK sent") as mock_send:
            result = runner.invoke(
                app,
                [
                    "send",
                    "--from",
                    "me@corp.com",
                    "--to",
                    "a@b.com",
                    "--subject",
                    "Hi",
                    "--body",
                    "Hello 🚀 world",
                    "-H",
                ],
            )
        assert result.exit_code == 0
        assert mock_send.call_args[1]["humanize"] is True
        with patch("imail.cli.mail.create_eml_draft", return_value="OK opened draft") as mock_draft:
            result = runner.invoke(
                app,
                [
                    "send",
                    "--from",
                    "me@corp.com",
                    "--to",
                    "a@b.com",
                    "--subject",
                    "Hi",
                    "--body",
                    "Hello",
                    "--open",
                ],
            )
        assert result.exit_code == 0
        assert "OK opened draft" in result.output
        assert mock_draft.call_args[1]["open_in_mail"] is True


class TestDraftCommand:
    def test_draft_cmd_saves_silent_draft(self) -> None:
        with patch("imail.cli.mail.save_silent_draft", return_value="OK draft saved quietly") as mock_save:
            result = runner.invoke(
                app,
                [
                    "draft",
                    "--from",
                    "me@corp.com",
                    "--to",
                    "a@b.com",
                    "--subject",
                    "Subj",
                    "--body",
                    "Body text",
                ],
            )
        assert result.exit_code == 0
        assert "OK draft saved quietly" in result.output
        assert mock_save.call_args[1]["to"] == "a@b.com"

    def test_draft_cmd_missing_body_file(self) -> None:
        result = runner.invoke(
            app,
            [
                "draft",
                "--from",
                "me@corp.com",
                "--to",
                "a@b.com",
                "--subject",
                "Subj",
                "--body-file",
                "/nonexistent/file.txt",
            ],
        )
        assert result.exit_code == 1
        assert "Body file not found" in result.output

    def test_draft_cmd_missing_body(self) -> None:
        result = runner.invoke(
            app,
            [
                "draft",
                "--from",
                "me@corp.com",
                "--to",
                "a@b.com",
                "--subject",
                "Subj",
            ],
        )
        assert result.exit_code == 1
        assert "Email body or body file is required" in result.output


class TestVersionCmd:
    def test_version_prints_version(self) -> None:
        from imail import __version__

        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert __version__ in result.output


class TestAgentCmds:
    def test_agent_schema(self) -> None:
        with patch("imail.cli.agent_mod.schema_json", return_value='{"tool":"imail"}'):
            result = runner.invoke(app, ["agent", "schema"])
        assert result.exit_code == 0
        assert json.loads(result.output)["tool"] == "imail"

    def test_agent_schema_missing_config(self) -> None:
        with patch(
            "imail.cli.agent_mod.schema_json",
            side_effect=FileNotFoundError("missing"),
        ):
            result = runner.invoke(app, ["agent", "schema"])
        assert result.exit_code == 1

    def test_agent_guide(self) -> None:
        with patch("imail.cli.agent_mod.guide_text", return_value="imail guide"):
            result = runner.invoke(app, ["agent", "guide"])
        assert result.exit_code == 0
        assert "imail guide" in result.output

    def test_agent_guide_missing_config(self) -> None:
        with patch(
            "imail.cli.agent_mod.guide_text",
            side_effect=FileNotFoundError("missing"),
        ):
            result = runner.invoke(app, ["agent", "guide"])
        assert result.exit_code == 1


class TestCliAutodraft:
    def test_autodraft_no_results(self) -> None:
        with patch("imail.autodraft.process_inbox_autodraft", return_value=[]):
            result = runner.invoke(app, ["autodraft"])
        assert result.exit_code == 0
        assert "No pending messages" in result.output

    def test_autodraft_with_results(self) -> None:
        items = [
            {
                "status": "drafted",
                "account": "michaelle.lubich@gmail.com",
                "recipient": "recruiter@example.com",
                "subject": "Re: Job opening",
            }
        ]
        with patch("imail.autodraft.process_inbox_autodraft", return_value=items) as mock_proc:
            result = runner.invoke(app, ["autodraft", "--account", "michaelle.lubich@gmail.com", "--limit", "10", "--dry-run"])
        assert result.exit_code == 0
        assert "[DRAFTED]" in result.output
        mock_proc.assert_called_once_with(accounts=["michaelle.lubich@gmail.com"], limit_per_account=10, dry_run=True)


class TestCliAutodraftEval:
    def test_autodraft_eval_passes_prints_table_and_exits_zero(self) -> None:
        results = [
            {"case": "c1", "needs_reply": True, "stakes": "low", "confidence": 0.9,
             "action": "draft", "unsafe_send": False, "passed": True, "reason": ""},
        ]
        with patch("imail.autodraft_eval.load_cases", return_value=[{"case": "c1"}]), \
             patch("imail.autodraft_eval.run_eval", return_value=results):
            result = runner.invoke(app, ["autodraft-eval"])
        assert result.exit_code == 0
        assert "c1" in result.output
        assert "1/1 passed, 0 unsafe sends" in result.output

    def test_autodraft_eval_unsafe_send_exits_nonzero(self) -> None:
        results = [
            {"case": "c1", "needs_reply": True, "stakes": "low", "confidence": 0.99,
             "action": "send", "unsafe_send": True, "passed": False, "reason": ""},
        ]
        with patch("imail.autodraft_eval.load_cases", return_value=[{"case": "c1"}]), \
             patch("imail.autodraft_eval.run_eval", return_value=results):
            result = runner.invoke(app, ["autodraft-eval"])
        assert result.exit_code == 1
        assert "1 unsafe sends" in result.output


class TestCliAutodraftLog:
    def test_autodraft_log_prints_formatted_output(self) -> None:
        with patch("imail.autodraft.format_recent_log", return_value="one line of log") as mock_fmt:
            result = runner.invoke(app, ["autodraft-log", "-n", "5"])
        assert result.exit_code == 0
        assert "one line of log" in result.output
        mock_fmt.assert_called_once_with(5)

    def test_autodraft_log_default_limit(self) -> None:
        with patch("imail.autodraft.format_recent_log", return_value="") as mock_fmt:
            result = runner.invoke(app, ["autodraft-log"])
        assert result.exit_code == 0
        mock_fmt.assert_called_once_with(20)


class TestMainEntry:
    def test_main_invokes_app(self) -> None:
        from imail.cli import main

        with patch("imail.cli.app") as mock_app:
            main()
        mock_app.assert_called_once()
