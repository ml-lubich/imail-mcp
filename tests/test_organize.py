"""Tests for imail.organize — classify, aliases, organize_inboxes."""

from __future__ import annotations

import io
from unittest.mock import patch

import pytest

from imail import organize


class TestClassify:
    def test_returns_security_folder_when_available(self) -> None:
        folders = set(organize.FOLDERS)
        assert organize.classify("security alert: unusual activity", folders) == "Security"

    def test_returns_meetings_folder_for_invitation(self) -> None:
        folders = set(organize.FOLDERS)
        assert organize.classify("Invitation: Team sync", folders) == "Meetings"

    def test_returns_it_folder_for_itsupport(self) -> None:
        folders = set(organize.FOLDERS)
        assert organize.classify("ITSUPPORT-12345 ticket", folders) == "IT"

    def test_returns_releases_folder_for_wint(self) -> None:
        folders = set(organize.FOLDERS)
        assert organize.classify("WINT release notes", folders) == "Releases"

    def test_job_applications_falls_back_to_fyi_when_folder_missing(self) -> None:
        folders = {"FYI", "INBOX"}
        assert organize.classify("Urgent Opening: Python dev", folders) == "FYI"

    def test_job_applications_uses_folder_when_present(self) -> None:
        folders = set(organize.FOLDERS)
        assert organize.classify("thank you for your application", folders) == "Job Applications"

    def test_personal_folder_for_fastrak(self) -> None:
        folders = set(organize.FOLDERS)
        assert organize.classify("FasTrak toll notice", folders) == "Personal"

    def test_action_folder_for_action_required(self) -> None:
        folders = set(organize.FOLDERS)
        assert organize.classify("action required: review docs", folders) == "Action"

    def test_fyi_folder_for_newsletter(self) -> None:
        folders = set(organize.FOLDERS)
        assert organize.classify("weekly update newsletter", folders) == "FYI"

    def test_returns_none_when_no_rule_matches(self) -> None:
        folders = set(organize.FOLDERS)
        assert organize.classify("xyzzy totally random subject", folders) is None

    def test_returns_fyi_when_matched_folder_missing(self) -> None:
        assert organize.classify("security alert", {"FYI", "INBOX"}) == "FYI"

    def test_returns_none_when_matched_folder_unavailable_and_no_fyi(self) -> None:
        assert organize.classify("security alert", {"INBOX"}) is None

    def test_empty_subject_still_matches_fyi_patterns(self) -> None:
        folders = set(organize.FOLDERS)
        assert organize.classify("", folders) is None


class TestInboxName:
    def test_prefers_inbox_uppercase(self) -> None:
        assert organize.inbox_name({"Archive", "INBOX", "Inbox"}) == "INBOX"

    def test_falls_back_to_inbox_mixed_case(self) -> None:
        assert organize.inbox_name({"Archive", "Inbox"}) == "Inbox"

    def test_returns_none_when_no_inbox(self) -> None:
        assert organize.inbox_name({"Archive", "Sent"}) is None


class TestResolveAccountAlias:
    def test_resolves_google_alias(self) -> None:
        assert organize.resolve_account_alias("google") == "Google"

    def test_resolves_case_insensitive_alias(self) -> None:
        assert organize.resolve_account_alias("POLARIS") == "Exchange"

    def test_returns_name_when_no_alias(self) -> None:
        assert organize.resolve_account_alias("UnknownAccount") == "UnknownAccount"


class TestEnsureFolders:
    def test_skips_existing_and_job_applications(self) -> None:
        existing = set(organize.FOLDERS) | {"INBOX"}
        with patch.object(organize, "run_as") as mock_run:
            result = organize.ensure_folders("Google", existing.copy())
        mock_run.assert_not_called()
        assert "Action" in result

    def test_creates_missing_folder_via_run_as(self) -> None:
        existing: set[str] = {"INBOX"}
        with patch.object(organize, "run_as") as mock_run:
            result = organize.ensure_folders("Google", existing)
        assert mock_run.call_count == len(organize.FOLDERS) - 1  # minus Job Applications
        assert "Action" in result

    def test_ignores_run_as_exception(self) -> None:
        existing: set[str] = {"INBOX"}
        with patch.object(organize, "run_as", side_effect=RuntimeError("fail")):
            result = organize.ensure_folders("Google", existing)
        assert result == existing


class TestFetchSubjects:
    def test_parses_valid_tab_separated_rows(self) -> None:
        with patch.object(organize, "run_as", return_value="1\tHello\n2\tWorld\n"):
            rows = organize.fetch_subjects("Google", "INBOX", 10)
        assert rows == [(1, "Hello"), (2, "World")]

    def test_skips_malformed_lines(self) -> None:
        with patch.object(organize, "run_as", return_value="badline\n1\tOk\nx\ty\n"):
            rows = organize.fetch_subjects("Google", "INBOX", 10)
        assert rows == [(1, "Ok")]


class TestListAccountsAndMailboxes:
    def test_list_accounts_parses_output(self) -> None:
        with patch.object(
            organize,
            "run_as",
            return_value="Google\tuser@gmail.com\nExchange\twork@corp.com\n",
        ):
            rows = organize.list_accounts()
        assert rows == [("Google", "user@gmail.com"), ("Exchange", "work@corp.com")]

    def test_list_mailbox_names_parses_output(self) -> None:
        with patch.object(organize, "run_as", return_value="INBOX\nAction\n\n"):
            boxes = organize.list_mailbox_names("Google")
        assert boxes == {"INBOX", "Action"}


class TestMoveIndex:
    def test_calls_run_as_with_move_script(self) -> None:
        with patch.object(organize, "run_as") as mock_run:
            organize.move_index("Google", "INBOX", 3, "Action")
        mock_run.assert_called_once()
        assert "move m to destBox" in mock_run.call_args[0][0]


class TestOrganizeInboxes:
    @pytest.fixture
    def mock_mail_ops(self):
        with (
            patch.object(organize, "list_accounts") as list_accts,
            patch.object(organize, "list_mailbox_names") as list_boxes,
            patch.object(organize, "ensure_folders") as ensure,
            patch.object(organize, "fetch_subjects") as fetch,
            patch.object(organize, "move_index") as move,
            patch.object(organize, "resolve_account_alias", side_effect=lambda x: x),
        ):
            list_accts.return_value = [("Google", "user@gmail.com")]
            list_boxes.return_value = {"INBOX", "FYI", "Action"}
            ensure.side_effect = lambda _a, boxes: boxes
            fetch.return_value = [(1, "action required: sign form")]
            yield {
                "list_accts": list_accts,
                "list_boxes": list_boxes,
                "ensure": ensure,
                "fetch": fetch,
                "move": move,
            }

    def test_organize_moves_matching_messages(self, mock_mail_ops) -> None:
        buf = io.StringIO()
        code = organize.organize_inboxes(limit=50, out=buf)
        assert code == 0
        mock_mail_ops["move"].assert_called_once()
        assert "moved=1" in buf.getvalue()
        assert "OK — nothing deleted" in buf.getvalue()

    def test_organize_returns_2_for_unknown_account(self) -> None:
        with (
            patch.object(organize, "list_accounts", return_value=[("Google", "a@b.com")]),
            patch.object(organize, "resolve_account_alias", return_value="Missing"),
        ):
            code = organize.organize_inboxes(account="missing", out=io.StringIO())
        assert code == 2

    def test_organize_skips_when_boxes_fail(self, mock_mail_ops) -> None:
        mock_mail_ops["list_boxes"].side_effect = RuntimeError("no mail")
        buf = io.StringIO()
        code = organize.organize_inboxes(out=buf)
        assert code == 0
        assert "SKIP boxes" in buf.getvalue()

    def test_organize_skips_when_no_inbox(self, mock_mail_ops) -> None:
        mock_mail_ops["list_boxes"].return_value = {"Sent"}
        mock_mail_ops["ensure"].return_value = {"Sent"}
        buf = io.StringIO()
        code = organize.organize_inboxes(out=buf)
        assert code == 0
        assert "SKIP: no Inbox/INBOX" in buf.getvalue()

    def test_organize_skips_when_fetch_fails(self, mock_mail_ops) -> None:
        mock_mail_ops["fetch"].side_effect = RuntimeError("fetch fail")
        buf = io.StringIO()
        code = organize.organize_inboxes(out=buf)
        assert code == 0
        assert "SKIP fetch" in buf.getvalue()

    def test_organize_reports_move_failures(self, mock_mail_ops) -> None:
        mock_mail_ops["move"].side_effect = RuntimeError("move fail")
        buf = io.StringIO()
        code = organize.organize_inboxes(out=buf)
        assert code == 0
        assert "FAIL move" in buf.getvalue()
        assert "moved=0" in buf.getvalue()

    def test_organize_filters_by_account_name(self, mock_mail_ops) -> None:
        mock_mail_ops["list_accts"].return_value = [
            ("Google", "user@gmail.com"),
            ("Exchange", "work@corp.com"),
        ]
        with patch.object(organize, "resolve_account_alias", return_value="Google"):
            organize.organize_inboxes(account="google", out=io.StringIO())
        assert mock_mail_ops["list_boxes"].call_count == 1
