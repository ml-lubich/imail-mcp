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

    def test_list_with_query(self) -> None:
        rows = [{"index": "1", "date": "d", "sender": "delta", "subject": "flight"}]
        with patch("imail.cli.mail.list_messages", return_value=rows) as mock_list:
            result = runner.invoke(app, ["list", "--query", "flight", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == rows
        mock_list.assert_called_once_with(account="", mailbox="INBOX", limit=20, query="flight")

    def test_list_failure(self) -> None:
        with patch(
            "imail.cli.mail.format_list_messages",
            side_effect=RuntimeError("list fail"),
        ):
            result = runner.invoke(app, ["list"])
        assert result.exit_code == 1


class TestSearchCmd:
    def test_search_success_text(self) -> None:
        with patch("imail.cli.mail.format_list_messages", return_value="1\tSubject") as mock_fmt:
            result = runner.invoke(app, ["search", "Apple Card"])
        assert result.exit_code == 0
        assert "1\tSubject" in result.output
        mock_fmt.assert_called_once_with(account="", mailbox="INBOX", limit=20, query="Apple Card")

    def test_search_success_json(self) -> None:
        rows = [{"index": "1", "date": "d", "sender": "support", "subject": "Apple Card"}]
        with patch("imail.cli.mail.list_messages", return_value=rows) as mock_list:
            result = runner.invoke(app, ["search", "Apple Card", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == rows
        mock_list.assert_called_once_with(account="", mailbox="INBOX", limit=20, query="Apple Card")

    def test_search_failure(self) -> None:
        with patch(
            "imail.cli.mail.format_list_messages",
            side_effect=RuntimeError("search fail"),
        ):
            result = runner.invoke(app, ["search", "Apple Card"])
        assert result.exit_code == 1


class TestReadCmd:
    def test_read_success_text(self) -> None:
        msg = {
            "id": "123",
            "message_id": "mid@corp",
            "date": "Oct 4",
            "sender": "sender@corp.com",
            "reply_to": "reply@corp.com",
            "subject": "Hello World",
            "was_replied_to": False,
            "attachment_count": 1,
            "attachments": ["evidence.pdf"],
            "body": "This is message body",
        }
        with patch("imail.cli.mail.read_message", return_value=msg) as mock_read:
            result = runner.invoke(app, ["read", "1", "-a", "google"])
        assert result.exit_code == 0
        assert "ID:          123" in result.output
        assert "From:        sender@corp.com" in result.output
        assert "Reply-To:    reply@corp.com" in result.output
        assert "evidence.pdf" in result.output
        assert "This is message body" in result.output
        mock_read.assert_called_once_with(account="google", index=1, mailbox="INBOX")

    def test_read_success_json(self) -> None:
        msg = {
            "id": "123",
            "message_id": "mid@corp",
            "date": "Oct 4",
            "sender": "sender@corp.com",
            "reply_to": "reply@corp.com",
            "subject": "Hello World",
            "was_replied_to": False,
            "attachment_count": 0,
            "attachments": [],
            "body": "Body content",
        }
        with patch("imail.cli.mail.read_message", return_value=msg):
            result = runner.invoke(app, ["read", "1", "-j"])
        assert result.exit_code == 0
        assert json.loads(result.output) == msg

    def test_read_failure(self) -> None:
        with patch("imail.cli.mail.read_message", side_effect=RuntimeError("msg not found")):
            result = runner.invoke(app, ["read", "99"])
        assert result.exit_code == 1
        assert "FAIL: msg not found" in result.output


class TestReplyCmd:
    def test_reply_success(self) -> None:
        with patch("imail.cli.mail.reply_message", return_value="OK sent to reply@corp.com (verified)") as mock_reply:
            result = runner.invoke(
                app,
                [
                    "reply",
                    "1",
                    "--account",
                    "google",
                    "--expected-recipient",
                    "reply@corp.com",
                    "-b",
                    "Replying to your email",
                    "--attach",
                    "/tmp/doc.pdf",
                ],
            )
        assert result.exit_code == 0
        assert "OK sent to reply@corp.com" in result.output
        mock_reply.assert_called_once_with(
            account="google",
            index=1,
            mailbox="INBOX",
            body="Replying to your email",
            attachments=["/tmp/doc.pdf"],
            from_addr="",
            to="",
            cc="",
            subject="",
            markdown=True,
            zip_attachments=False,
            humanize=False,
            open_draft=False,
            expected_recipient="reply@corp.com",
            expected_sender="",
            expected_message_id="",
            max_retries=1,
        )

    def test_reply_with_body_file(self, tmp_path) -> None:
        bf = tmp_path / "reply.md"
        bf.write_text("Markdown reply content", encoding="utf-8")
        with patch("imail.cli.mail.reply_message", return_value="OK sent") as mock_reply:
            result = runner.invoke(
                app,
                [
                    "reply",
                    "2",
                    "--body-file",
                    str(bf),
                ],
            )
        assert result.exit_code == 0
        mock_reply.assert_called_once_with(
            account="",
            index=2,
            mailbox="INBOX",
            body="Markdown reply content",
            attachments=None,
            from_addr="",
            to="",
            cc="",
            subject="",
            markdown=True,
            zip_attachments=False,
            humanize=False,
            open_draft=False,
            expected_recipient="",
            expected_sender="",
            expected_message_id="",
            max_retries=1,
        )

    def test_reply_missing_body(self) -> None:
        result = runner.invoke(app, ["reply", "1"])
        assert result.exit_code == 1
        assert "Reply body or body file is required" in result.output

    def test_reply_body_file_not_found(self) -> None:
        result = runner.invoke(app, ["reply", "1", "--body-file", "/nonexistent/reply.txt"])
        assert result.exit_code == 1
        assert "Body file not found" in result.output

    def test_reply_body_as_file_path(self, tmp_path) -> None:
        bf = tmp_path / "reply.txt"
        bf.write_text("File body text", encoding="utf-8")
        with patch("imail.cli.mail.reply_message", return_value="OK sent") as mock_reply:
            result = runner.invoke(app, ["reply", "1", "-b", str(bf)])
        assert result.exit_code == 0
        mock_reply.assert_called_once()
        assert mock_reply.call_args.kwargs["body"] == "File body text"

    def test_reply_failure(self) -> None:
        with patch("imail.cli.mail.reply_message", side_effect=RuntimeError("reply failed")):
            result = runner.invoke(app, ["reply", "1", "-b", "test"])
        assert result.exit_code == 1
        assert "FAIL: reply failed" in result.output

    def test_reply_unreadable_body_path_is_treated_as_inline_body(self) -> None:
        from pathlib import Path

        with (
            patch.object(Path, "is_file", side_effect=OSError("unreadable path")),
            patch("imail.cli.mail.reply_message", return_value="OK sent") as mock_reply,
        ):
            result = runner.invoke(app, ["reply", "1", "--body", "x" * 5000])
        assert result.exit_code == 0
        assert mock_reply.call_args.kwargs["body"] == "x" * 5000


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

    def test_send_long_literal_body_that_is_not_a_path(self) -> None:
        body = "body text " * 1000
        from pathlib import Path

        with (
            patch.object(Path, "is_file", side_effect=OSError("path too long")),
            patch("imail.cli.mail.send_message", return_value="OK sent") as mock_send,
        ):
            result = runner.invoke(
                app,
                ["send", "--from", "me@example.com", "--to", "you@example.com",
                 "--subject", "Test", "--body", body],
            )
        assert result.exit_code == 0
        assert mock_send.call_args.kwargs["body"] == body

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

    def test_send_markdown_existing_file_enables_markdown(self, tmp_path: Path) -> None:
        body_file = tmp_path / "message.md"
        body_file.write_text("# Markdown")
        with patch("imail.cli.mail.send_message", return_value="OK sent") as mock_send:
            result = runner.invoke(
                app,
                ["send", "--from", "me@example.com", "--to", "you@example.com",
                 "--subject", "Test", "--body", str(body_file)],
            )
        assert result.exit_code == 0
        assert mock_send.call_args.kwargs["is_markdown"] is True

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

    def test_send_queued_in_outbox_exits_nonzero(self) -> None:
        with patch("imail.cli.mail.send_message", return_value="QUEUED in Outbox for a@b.com (pending network/Mail send)"):
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
        assert result.exit_code == 1
        assert "ERROR: Delivery is unverified" in result.output



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


class TestOutreachDraft:
    def test_outreach_draft_help(self) -> None:
        result = runner.invoke(app, ["outreach", "draft", "-h"])
        assert result.exit_code == 0
        assert "--config" in result.output and "--input" in result.output

    def test_outreach_draft_loads_config_and_input_and_prints_json(self, tmp_path) -> None:
        config = tmp_path / "config.json"
        data = tmp_path / "input.json"
        config.write_text(json.dumps({"enabled": True, "sign_as": "Referral Sender"}))
        data.write_text(json.dumps({
            "company": "Acme",
            "contact_name": "Taylor",
            "role": "Applied AI Engineer",
            "role_description": "Build agents",
            "candidate_name": "Jordan",
            "candidate_facts": [{"id": "f1", "text": "Jordan ships agents."}],
            "company_evidence": [{
                "id": "e1", "text": "Acme builds agents",
                "source_url": "https://example.com/role", "observed_at": "2026-10-23",
            }],
            "candidate_email": "jordan@example.com",
        }))
        expected = {"body": "hi Taylor"}
        with patch("imail.cli.outreach.draft_outreach", return_value=expected) as draft:
            result = runner.invoke(app, ["outreach", "draft", "--config", str(config), "--input", str(data)])
        assert result.exit_code == 0
        assert json.loads(result.output) == expected
        assert draft.call_args.kwargs["company"] == "Acme"
        assert draft.call_args.kwargs["config"]["sign_as"] == "Referral Sender"

    def test_outreach_draft_disabled_returns_no_model_call(self, tmp_path) -> None:
        config = tmp_path / "config.json"
        data = tmp_path / "input.json"
        config.write_text(json.dumps({"enabled": False}))
        data.write_text("{}")
        result = runner.invoke(app, ["outreach", "draft", "--config", str(config), "--input", str(data)])
        assert result.exit_code == 0
        assert json.loads(result.output) is None

    def test_outreach_draft_reports_provider_failure_without_traceback(self, tmp_path) -> None:
        config = tmp_path / "config.json"
        data = tmp_path / "input.json"
        config.write_text(json.dumps({"enabled": True}))
        data.write_text(json.dumps({
            "company": "Acme", "contact_name": "Taylor", "role": "Engineer",
            "role_description": "Build things", "candidate_name": "Jordan",
            "candidate_facts": [{"id": "f1", "text": "ships software"}],
            "company_evidence": [{"id": "e1", "text": "builds software", "source_url": "https://example.com", "observed_at": "2026-10-23"}],
        }))
        with patch("imail.cli.outreach.draft_outreach", side_effect=RuntimeError("provider unavailable")):
            result = runner.invoke(app, ["outreach", "draft", "--config", str(config), "--input", str(data)])
        assert result.exit_code == 1
        assert "FAIL: provider unavailable" in result.output
        assert "Traceback" not in result.output
