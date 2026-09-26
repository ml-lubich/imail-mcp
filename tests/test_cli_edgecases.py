"""Edge-case command x flag matrix for imail.cli.

Covers required-option enforcement, type validation, numeric boundaries,
unicode/shell-metacharacter passthrough, body/body-file precedence,
missing-file handling, repeatable options, batch/status edge cases, and
per-command --help/-h option coverage. Every mocked call goes through the
same imail.mail / imail.organize / imail.batch / imail.autodraft / imail.agent
/ imail.mcp seams the existing test files use -- no real osascript call is
ever reachable from here.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from imail import __version__
from imail.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# 1. Missing required options
# ---------------------------------------------------------------------------


class TestSendMissingRequired:
    def test_send_missing_from(self) -> None:
        result = runner.invoke(app, ["send", "--to", "a@b.com", "--subject", "Hi", "--body", "x"])
        assert result.exit_code == 2
        assert "--from" in result.output

    def test_send_missing_to(self) -> None:
        result = runner.invoke(app, ["send", "--from", "me@corp.com", "--subject", "Hi", "--body", "x"])
        assert result.exit_code == 2
        assert "--to" in result.output

    def test_send_missing_subject(self) -> None:
        result = runner.invoke(app, ["send", "--from", "me@corp.com", "--to", "a@b.com", "--body", "x"])
        assert result.exit_code == 2
        assert "--subject" in result.output

    def test_send_missing_all_required(self) -> None:
        result = runner.invoke(app, ["send"])
        assert result.exit_code == 2
        assert "Missing option" in result.output


class TestDraftMissingRequired:
    def test_draft_missing_to(self) -> None:
        result = runner.invoke(app, ["draft", "--subject", "Hi", "--body", "x"])
        assert result.exit_code == 2
        assert "--to" in result.output

    def test_draft_missing_subject(self) -> None:
        result = runner.invoke(app, ["draft", "--to", "a@b.com", "--body", "x"])
        assert result.exit_code == 2
        assert "--subject" in result.output


# ---------------------------------------------------------------------------
# 2. Invalid option value types
# ---------------------------------------------------------------------------


class TestInvalidValueTypes:
    def test_list_limit_not_int(self) -> None:
        result = runner.invoke(app, ["list", "--limit", "abc"])
        assert result.exit_code == 2
        assert "not a valid int" in result.output

    def test_organize_limit_not_int(self) -> None:
        result = runner.invoke(app, ["organize", "--limit", "abc"])
        assert result.exit_code == 2
        assert "not a valid int" in result.output

    def test_autodraft_limit_not_int(self) -> None:
        result = runner.invoke(app, ["autodraft", "--limit", "abc"])
        assert result.exit_code == 2
        assert "not a valid int" in result.output

    def test_autodraft_log_n_not_int(self) -> None:
        result = runner.invoke(app, ["autodraft-log", "-n", "abc"])
        assert result.exit_code == 2
        assert "not a valid int" in result.output

    def test_batch_limit_not_int(self) -> None:
        result = runner.invoke(app, ["batch", "--limit", "abc"])
        assert result.exit_code == 2
        assert "not a valid int" in result.output

    def test_batch_min_delay_not_float(self) -> None:
        result = runner.invoke(app, ["batch", "--min-delay", "abc"])
        assert result.exit_code == 2
        assert "not a valid float" in result.output

    def test_batch_max_delay_not_float(self) -> None:
        result = runner.invoke(app, ["batch", "--max-delay", "abc"])
        assert result.exit_code == 2
        assert "not a valid float" in result.output


# ---------------------------------------------------------------------------
# 3. Numeric boundary passthrough (no silent clamping)
# ---------------------------------------------------------------------------


class TestLimitBoundaries:
    def test_list_limit_zero(self) -> None:
        with patch("imail.cli.mail.format_list_messages", return_value="") as mock_fn:
            result = runner.invoke(app, ["list", "--limit", "0"])
        assert result.exit_code == 0
        assert mock_fn.call_args[1]["limit"] == 0

    def test_list_limit_negative(self) -> None:
        with patch("imail.cli.mail.format_list_messages", return_value="") as mock_fn:
            result = runner.invoke(app, ["list", "--limit", "-1"])
        assert result.exit_code == 0
        assert mock_fn.call_args[1]["limit"] == -1

    def test_list_limit_huge(self) -> None:
        with patch("imail.cli.mail.format_list_messages", return_value="") as mock_fn:
            result = runner.invoke(app, ["list", "--limit", "999999999"])
        assert result.exit_code == 0
        assert mock_fn.call_args[1]["limit"] == 999999999

    def test_organize_limit_zero(self) -> None:
        with patch("imail.cli.organize.organize_inboxes", return_value=0) as mock_fn:
            result = runner.invoke(app, ["organize", "--limit", "0"])
        assert result.exit_code == 0
        assert mock_fn.call_args[1]["limit"] == 0

    def test_organize_limit_negative(self) -> None:
        with patch("imail.cli.organize.organize_inboxes", return_value=0) as mock_fn:
            result = runner.invoke(app, ["organize", "--limit", "-1"])
        assert result.exit_code == 0
        assert mock_fn.call_args[1]["limit"] == -1

    def test_organize_limit_huge(self) -> None:
        with patch("imail.cli.organize.organize_inboxes", return_value=0) as mock_fn:
            result = runner.invoke(app, ["organize", "--limit", "999999999"])
        assert result.exit_code == 0
        assert mock_fn.call_args[1]["limit"] == 999999999

    def test_autodraft_limit_zero(self) -> None:
        with patch("imail.autodraft.process_inbox_autodraft", return_value=[]) as mock_fn:
            result = runner.invoke(app, ["autodraft", "--limit", "0"])
        assert result.exit_code == 0
        assert mock_fn.call_args[1]["limit_per_account"] == 0

    def test_autodraft_limit_negative(self) -> None:
        with patch("imail.autodraft.process_inbox_autodraft", return_value=[]) as mock_fn:
            result = runner.invoke(app, ["autodraft", "--limit", "-1"])
        assert result.exit_code == 0
        assert mock_fn.call_args[1]["limit_per_account"] == -1

    def test_autodraft_limit_huge(self) -> None:
        with patch("imail.autodraft.process_inbox_autodraft", return_value=[]) as mock_fn:
            result = runner.invoke(app, ["autodraft", "--limit", "999999999"])
        assert result.exit_code == 0
        assert mock_fn.call_args[1]["limit_per_account"] == 999999999

    def test_batch_limit_zero_means_no_limit_kwarg(self) -> None:
        with (
            patch("imail.batch.get_queue_summary", return_value={"total": 1, "pending": 1, "sent": 0, "failed": 0}),
            patch("imail.batch.run_batch_dispatch", return_value={"processed": 0, "sent": 0, "failed": 0}) as mock_run,
        ):
            result = runner.invoke(app, ["batch", "--limit", "0"])
        assert result.exit_code == 0
        assert mock_run.call_args[1]["limit"] is None

    def test_batch_limit_negative_means_no_limit_kwarg(self) -> None:
        with (
            patch("imail.batch.get_queue_summary", return_value={"total": 1, "pending": 1, "sent": 0, "failed": 0}),
            patch("imail.batch.run_batch_dispatch", return_value={"processed": 0, "sent": 0, "failed": 0}) as mock_run,
        ):
            result = runner.invoke(app, ["batch", "--limit", "-1"])
        assert result.exit_code == 0
        assert mock_run.call_args[1]["limit"] is None

    def test_batch_limit_huge_passthrough(self) -> None:
        with (
            patch("imail.batch.get_queue_summary", return_value={"total": 1, "pending": 1, "sent": 0, "failed": 0}),
            patch("imail.batch.run_batch_dispatch", return_value={"processed": 0, "sent": 0, "failed": 0}) as mock_run,
        ):
            result = runner.invoke(app, ["batch", "--limit", "999999999"])
        assert result.exit_code == 0
        assert mock_run.call_args[1]["limit"] == 999999999


# ---------------------------------------------------------------------------
# 4. --json vs plain output edge cases for `list`
# ---------------------------------------------------------------------------


class TestListOutputEdgeCases:
    def test_list_json_empty_is_exact_empty_array(self) -> None:
        with patch("imail.cli.mail.list_messages", return_value=[]):
            result = runner.invoke(app, ["list", "--json"])
        assert result.exit_code == 0
        assert result.output.strip() == "[]"

    def test_list_plain_with_tabs_and_newlines_not_corrupted(self) -> None:
        weird_row = "1\td\ts\tSubject\twith\ttabs\nand a newline"
        with patch("imail.cli.mail.format_list_messages", return_value=weird_row):
            result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert weird_row in result.output


# ---------------------------------------------------------------------------
# 5. Unicode / emoji / shell-metacharacter passthrough
# ---------------------------------------------------------------------------

NASTY_STRINGS = [
    "unicode-emoji-😀🎉日本語",
    "shell;`$(rm -rf /)`\"'\\",
]


class TestNastyStringPassthrough:
    def test_send_to_nasty(self) -> None:
        for s in NASTY_STRINGS:
            with patch("imail.cli.mail.send_message", return_value="OK") as mock_fn:
                result = runner.invoke(
                    app, ["send", "--from", "me@corp.com", "--to", s, "--subject", "s", "--body", "b"]
                )
            assert result.exit_code == 0, result.output
            assert mock_fn.call_args[1]["to"] == s

    def test_send_subject_nasty(self) -> None:
        for s in NASTY_STRINGS:
            with patch("imail.cli.mail.send_message", return_value="OK") as mock_fn:
                result = runner.invoke(
                    app, ["send", "--from", "me@corp.com", "--to", "a@b.com", "--subject", s, "--body", "b"]
                )
            assert result.exit_code == 0, result.output
            assert mock_fn.call_args[1]["subject"] == s

    def test_send_body_nasty_and_long(self) -> None:
        long_body = "x" * 50_000 + " 😀 " + "`ls`"
        with patch("imail.cli.mail.send_message", return_value="OK") as mock_fn:
            result = runner.invoke(
                app, ["send", "--from", "me@corp.com", "--to", "a@b.com", "--subject", "s", "--body", long_body]
            )
        assert result.exit_code == 0, result.output
        assert mock_fn.call_args[1]["body"] == long_body

    def test_send_from_nasty(self) -> None:
        for s in NASTY_STRINGS:
            with patch("imail.cli.mail.send_message", return_value="OK") as mock_fn:
                result = runner.invoke(
                    app, ["send", "--from", s, "--to", "a@b.com", "--subject", "s", "--body", "b"]
                )
            assert result.exit_code == 0, result.output
            assert mock_fn.call_args[1]["from_addr"] == s

    def test_send_cc_nasty(self) -> None:
        for s in NASTY_STRINGS:
            with patch("imail.cli.mail.send_message", return_value="OK") as mock_fn:
                result = runner.invoke(
                    app,
                    ["send", "--from", "me@corp.com", "--to", "a@b.com", "--subject", "s", "--body", "b", "--cc", s],
                )
            assert result.exit_code == 0, result.output
            assert mock_fn.call_args[1]["cc"] == s

    def test_draft_to_and_subject_nasty(self) -> None:
        for s in NASTY_STRINGS:
            with patch("imail.cli.mail.save_silent_draft", return_value="OK") as mock_fn:
                result = runner.invoke(app, ["draft", "--to", s, "--subject", s, "--body", "b"])
            assert result.exit_code == 0, result.output
            assert mock_fn.call_args[1]["to"] == s
            assert mock_fn.call_args[1]["subject"] == s

    def test_organize_account_nasty(self) -> None:
        for s in NASTY_STRINGS:
            with patch("imail.cli.organize.organize_inboxes", return_value=0) as mock_fn:
                result = runner.invoke(app, ["organize", "--account", s])
            assert result.exit_code == 0, result.output
            assert mock_fn.call_args[1]["account"] == s

    def test_autodraft_account_nasty(self) -> None:
        for s in NASTY_STRINGS:
            with patch("imail.autodraft.process_inbox_autodraft", return_value=[]) as mock_fn:
                result = runner.invoke(app, ["autodraft", "--account", s])
            assert result.exit_code == 0, result.output
            assert mock_fn.call_args[1]["accounts"] == [s]

    def test_list_account_nasty(self) -> None:
        for s in NASTY_STRINGS:
            with patch("imail.cli.mail.format_list_messages", return_value="") as mock_fn:
                result = runner.invoke(app, ["list", "--account", s])
            assert result.exit_code == 0, result.output
            assert mock_fn.call_args[1]["account"] == s


# ---------------------------------------------------------------------------
# 6. Body vs body-file precedence
# ---------------------------------------------------------------------------


class TestBodyBodyFilePrecedence:
    def test_send_both_body_and_body_file_prefers_file(self, tmp_path: Path) -> None:
        f = tmp_path / "body.txt"
        f.write_text("from the file")
        with patch("imail.cli.mail.send_message", return_value="OK") as mock_fn:
            result = runner.invoke(
                app,
                [
                    "send", "--from", "me@corp.com", "--to", "a@b.com", "--subject", "s",
                    "--body", "from the flag", "--body-file", str(f),
                ],
            )
        assert result.exit_code == 0, result.output
        assert mock_fn.call_args[1]["body"] == "from the file"

    def test_draft_both_body_and_body_file_prefers_file(self, tmp_path: Path) -> None:
        f = tmp_path / "body.txt"
        f.write_text("draft file content")
        with patch("imail.cli.mail.save_silent_draft", return_value="OK") as mock_fn:
            result = runner.invoke(
                app,
                [
                    "draft", "--to", "a@b.com", "--subject", "s",
                    "--body", "draft flag content", "--body-file", str(f),
                ],
            )
        assert result.exit_code == 0, result.output
        assert mock_fn.call_args[1]["body"] == "draft file content"


# ---------------------------------------------------------------------------
# 7. Nonexistent file paths -> clean errors, never a raw traceback
# ---------------------------------------------------------------------------


class TestNonexistentPaths:
    def test_draft_body_file_missing(self) -> None:
        result = runner.invoke(
            app, ["draft", "--to", "a@b.com", "--subject", "s", "--body-file", "/no/such/file.md"]
        )
        assert result.exit_code == 1
        assert "Body file not found" in result.output
        assert "Traceback" not in result.output

    def test_send_attach_missing_path_passes_through_to_backend(self) -> None:
        # cli.py does not validate --attach existence itself (mail.py owns that
        # boundary); the mocked backend still receives the path and the CLI
        # must not crash while getting there.
        with patch("imail.cli.mail.send_message", return_value="OK") as mock_fn:
            result = runner.invoke(
                app,
                [
                    "send", "--from", "me@corp.com", "--to", "a@b.com", "--subject", "s",
                    "--body", "b", "--attach", "/no/such/attachment.pdf",
                ],
            )
        assert result.exit_code == 0, result.output
        assert "Traceback" not in result.output
        assert mock_fn.call_args[1]["attachments"] == ["/no/such/attachment.pdf"]

    def test_draft_attach_missing_path_passes_through_to_backend(self) -> None:
        with patch("imail.cli.mail.save_silent_draft", return_value="OK") as mock_fn:
            result = runner.invoke(
                app, ["draft", "--to", "a@b.com", "--subject", "s", "--body", "b", "--attach", "/no/such/file.pdf"]
            )
        assert result.exit_code == 0, result.output
        assert "Traceback" not in result.output
        assert mock_fn.call_args[1]["attachments"] == ["/no/such/file.pdf"]

    def test_batch_file_missing(self) -> None:
        result = runner.invoke(app, ["batch", "--file", "/no/such/jobs.json"])
        assert result.exit_code == 1
        assert "Batch file not found" in result.output
        assert "Traceback" not in result.output

    def test_status_queue_file_missing_is_graceful(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist" / "queue.json"
        result = runner.invoke(app, ["status", "--queue-file", str(missing)])
        assert result.exit_code == 0
        assert "Total: 0" in result.output
        assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# 8. Repeatable --attach
# ---------------------------------------------------------------------------


class TestRepeatableAttach:
    def test_send_multiple_attach_preserves_order(self) -> None:
        with patch("imail.cli.mail.send_message", return_value="OK") as mock_fn:
            result = runner.invoke(
                app,
                [
                    "send", "--from", "me@corp.com", "--to", "a@b.com", "--subject", "s", "--body", "b",
                    "--attach", "/tmp/one.pdf", "--attach", "/tmp/two.pdf", "-a", "/tmp/three.pdf",
                ],
            )
        assert result.exit_code == 0, result.output
        assert mock_fn.call_args[1]["attachments"] == ["/tmp/one.pdf", "/tmp/two.pdf", "/tmp/three.pdf"]

    def test_draft_multiple_attach_preserves_order(self) -> None:
        with patch("imail.cli.mail.save_silent_draft", return_value="OK") as mock_fn:
            result = runner.invoke(
                app,
                [
                    "draft", "--to", "a@b.com", "--subject", "s", "--body", "b",
                    "-a", "/tmp/one.pdf", "-a", "/tmp/two.pdf",
                ],
            )
        assert result.exit_code == 0, result.output
        assert mock_fn.call_args[1]["attachments"] == ["/tmp/one.pdf", "/tmp/two.pdf"]


# ---------------------------------------------------------------------------
# 9. `batch` command edge cases
# ---------------------------------------------------------------------------


class TestBatchCommand:
    def test_batch_file_valid_json_array_enqueues(self, tmp_path: Path) -> None:
        jobs = [{"to": "a@b.com", "subject": "s1", "body": "b1"}]
        f = tmp_path / "jobs.json"
        f.write_text(json.dumps(jobs))
        with patch("imail.batch.enqueue_items", return_value=1) as mock_fn:
            result = runner.invoke(app, ["batch", "--file", str(f)])
        assert result.exit_code == 0, result.output
        assert "Enqueued 1 items" in result.output
        assert mock_fn.call_args[0][0] == jobs

    def test_batch_file_malformed_json_clean_error(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("{not valid json")
        result = runner.invoke(app, ["batch", "--file", str(f)])
        assert result.exit_code == 1
        assert "FAIL: Error parsing batch file" in result.output
        assert "Traceback" not in result.output
        # regression: the isinstance-check's own clean error must not also
        # get caught and appended as a second, empty "Error parsing" line
        assert result.output.count("FAIL:") == 1

    def test_batch_file_not_a_json_array_single_clean_error(self, tmp_path: Path) -> None:
        f = tmp_path / "notlist.json"
        f.write_text(json.dumps({"to": "a@b.com"}))
        result = runner.invoke(app, ["batch", "--file", str(f)])
        assert result.exit_code == 1
        assert "must contain a JSON array" in result.output
        assert result.output.count("FAIL:") == 1

    def test_batch_run_and_dry_run_together(self) -> None:
        with (
            patch("imail.batch.get_queue_summary", return_value={"total": 1, "pending": 1, "sent": 0, "failed": 0}),
            patch(
                "imail.batch.run_batch_dispatch", return_value={"processed": 1, "sent": 1, "failed": 0}
            ) as mock_run,
        ):
            result = runner.invoke(app, ["batch", "--run", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert mock_run.call_args[1]["dry_run"] is True

    def test_batch_clear(self) -> None:
        with patch("imail.batch.clear_queue", return_value=3):
            result = runner.invoke(app, ["batch", "--clear"])
        assert result.exit_code == 0
        assert "Cleared 3 items" in result.output

    def test_batch_run_with_no_pending_items(self) -> None:
        with patch("imail.batch.get_queue_summary", return_value={"total": 0, "pending": 0, "sent": 0, "failed": 0}):
            result = runner.invoke(app, ["batch", "--run"])
        assert result.exit_code == 0
        assert "No pending items" in result.output


# ---------------------------------------------------------------------------
# 10. `status` with a real (missing) queue file -- already covered above,
#     this adds a real populated queue to prove the summary line is correct.
# ---------------------------------------------------------------------------


class TestStatusCommand:
    def test_status_with_real_populated_queue_file(self, tmp_path: Path) -> None:
        q = tmp_path / "queue.json"
        q.write_text(
            json.dumps(
                [
                    {"to": "a@b.com", "subject": "s1", "status": "sent"},
                    {"to": "c@d.com", "subject": "s2", "status": "pending"},
                ]
            )
        )
        result = runner.invoke(app, ["status", "--queue-file", str(q)])
        assert result.exit_code == 0
        assert "Total: 2" in result.output
        assert "Pending: 1" in result.output
        assert "Sent: 1" in result.output


# ---------------------------------------------------------------------------
# 11. `version` exact match against the installed package version
# ---------------------------------------------------------------------------


class TestVersionExact:
    def test_version_stdout_is_exactly_the_version(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert result.output == f"{__version__}\n"


# ---------------------------------------------------------------------------
# 12. `mcp` command never starts a real stdio server under test
# ---------------------------------------------------------------------------


class TestMcpCommand:
    def test_mcp_cmd_calls_run_server_with_no_args(self) -> None:
        with patch("imail.mcp.run_server") as mock_run:
            result = runner.invoke(app, ["mcp"])
        assert result.exit_code == 0
        mock_run.assert_called_once_with()


# ---------------------------------------------------------------------------
# 13. agent schema/guide with accounts.json missing at the deeper seam
# ---------------------------------------------------------------------------


class TestAgentMissingAccountsConfig:
    def test_agent_schema_missing_accounts_json_clean_exit(self) -> None:
        with patch("imail.agent.load_accounts_config", side_effect=FileNotFoundError("accounts.json missing")):
            result = runner.invoke(app, ["agent", "schema"])
        assert result.exit_code == 1
        assert "Traceback" not in result.output
        assert "FAIL:" in result.output

    def test_agent_guide_missing_accounts_json_clean_exit(self) -> None:
        with patch("imail.agent.load_accounts_config", side_effect=FileNotFoundError("accounts.json missing")):
            result = runner.invoke(app, ["agent", "guide"])
        assert result.exit_code == 1
        assert "Traceback" not in result.output
        assert "FAIL:" in result.output


# ---------------------------------------------------------------------------
# 14. NO_COLOR env var
# ---------------------------------------------------------------------------


class TestNoColorEnv:
    def test_help_with_no_color_env(self) -> None:
        colored_runner = CliRunner(env={"NO_COLOR": "1"})
        result = colored_runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    def test_real_command_with_no_color_env(self) -> None:
        colored_runner = CliRunner(env={"NO_COLOR": "1"})
        with patch("imail.cli.mail.format_accounts", return_value="A\ta@b.com"):
            result = colored_runner.invoke(app, ["accounts"])
        assert result.exit_code == 0

    def test_real_command_without_no_color_env(self) -> None:
        with patch("imail.cli.mail.format_accounts", return_value="A\ta@b.com"):
            result = runner.invoke(app, ["accounts"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# 15. Per-command --help / -h list their own option names
# ---------------------------------------------------------------------------


class TestHelpListsOwnOptions:
    def test_list_help_lists_its_options(self) -> None:
        for flag in ("--help", "-h"):
            result = runner.invoke(app, ["list", flag])
            assert result.exit_code == 0
            for opt in ("--account", "--mailbox", "--limit", "--json"):
                assert opt in result.output, f"{opt} missing from `list {flag}`"

    def test_organize_help_lists_its_options(self) -> None:
        for flag in ("--help", "-h"):
            result = runner.invoke(app, ["organize", flag])
            assert result.exit_code == 0
            for opt in ("--account", "-a", "--limit", "-n"):
                assert opt in result.output, f"{opt} missing from `organize {flag}`"

    def test_autodraft_help_lists_its_options(self) -> None:
        for flag in ("--help", "-h"):
            result = runner.invoke(app, ["autodraft", flag])
            assert result.exit_code == 0
            for opt in ("--account", "--limit", "--dry-run"):
                assert opt in result.output, f"{opt} missing from `autodraft {flag}`"

    def test_autodraft_log_help_lists_its_options(self) -> None:
        for flag in ("--help", "-h"):
            result = runner.invoke(app, ["autodraft-log", flag])
            assert result.exit_code == 0
            for opt in ("-n", "--limit"):
                assert opt in result.output, f"{opt} missing from `autodraft-log {flag}`"

    def test_send_help_lists_its_options(self) -> None:
        for flag in ("--help", "-h"):
            result = runner.invoke(app, ["send", flag])
            assert result.exit_code == 0
            for opt in (
                "--from", "--to", "--subject", "--body", "--body-file",
                "--cc", "--attach", "--markdown", "--zip-attachments",
                "--open", "--humanize",
            ):
                assert opt in result.output, f"{opt} missing from `send {flag}`"

    def test_draft_help_lists_its_options(self) -> None:
        for flag in ("--help", "-h"):
            result = runner.invoke(app, ["draft", flag])
            assert result.exit_code == 0
            for opt in ("--to", "--subject", "--body", "--body-file", "--from", "--cc", "--attach", "--humanize"):
                assert opt in result.output, f"{opt} missing from `draft {flag}`"

    def test_status_help_lists_its_options(self) -> None:
        for flag in ("--help", "-h"):
            result = runner.invoke(app, ["status", flag])
            assert result.exit_code == 0
            assert "--queue-file" in result.output

    def test_batch_help_lists_its_options(self) -> None:
        for flag in ("--help", "-h"):
            result = runner.invoke(app, ["batch", flag])
            assert result.exit_code == 0
            for opt in (
                "--file", "--run", "--limit", "--min-delay", "--max-delay",
                "--clear", "--dry-run", "--queue-file",
            ):
                assert opt in result.output, f"{opt} missing from `batch {flag}`"

    def test_mcp_help_exits_zero(self) -> None:
        for flag in ("--help", "-h"):
            result = runner.invoke(app, ["mcp", flag])
            assert result.exit_code == 0

    def test_agent_schema_and_guide_help_exit_zero(self) -> None:
        for sub in ("schema", "guide"):
            for flag in ("--help", "-h"):
                result = runner.invoke(app, ["agent", sub, flag])
                assert result.exit_code == 0
