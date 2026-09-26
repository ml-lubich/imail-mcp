"""Regression / edge-case tests for imail.organize, imail.batch, imail.agent.

New coverage only — see tests/test_organize.py, tests/test_batch.py and
tests/test_agent.py for the boundaries already exercised there. Every
AppleScript-touching call (`run_as`) is mocked; no real osascript/Mail.app
call and no real `time.sleep` of meaningful duration ever happens here.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from imail import agent, batch, organize


# ---------------------------------------------------------------------------
# organize.classify — full rule-table coverage
# ---------------------------------------------------------------------------

CATEGORY_PHRASES = [
    ("Security", "phishing attempt detected"),
    ("Meetings", "Zoom Meeting invite for standup"),
    ("IT", "Egnyte access renewed"),
    ("Releases", "CROWD_2024 rollout"),
    ("Job Applications", "Handshake AI job digest"),
    ("Personal", "Your Venmo payment received"),
    ("Action", "Please reply with your availability"),
    ("FYI", "Quarterly newsletter digest"),
]


class TestClassifyPerCategory:
    @pytest.mark.parametrize("folder,phrase", CATEGORY_PHRASES)
    def test_subject_matches_only_its_category(self, folder: str, phrase: str) -> None:
        assert organize.classify(phrase, set(organize.FOLDERS)) == folder

    @pytest.mark.parametrize("folder,phrase", CATEGORY_PHRASES)
    def test_sender_field_alone_triggers_match(self, folder: str, phrase: str) -> None:
        assert (
            organize.classify("no match here at all", set(organize.FOLDERS), sender=phrase)
            == folder
        )

    @pytest.mark.parametrize("folder,phrase", CATEGORY_PHRASES)
    def test_matches_uppercase_variant(self, folder: str, phrase: str) -> None:
        assert organize.classify(phrase.upper(), set(organize.FOLDERS)) == folder

    @pytest.mark.parametrize("folder,phrase", CATEGORY_PHRASES)
    def test_matches_lowercase_variant(self, folder: str, phrase: str) -> None:
        assert organize.classify(phrase.lower(), set(organize.FOLDERS)) == folder


class TestClassifyPriorityOrder:
    """RULES is a list — first pattern to match in list order wins.

    Verified from source order: Security, Meetings, IT, Releases,
    Job Applications, Personal, Action, FYI.
    """

    @pytest.mark.parametrize(
        "subj,expected",
        [
            ("phishing attempt during Zoom Meeting", "Security"),
            ("Zoom Meeting to discuss Egnyte access", "Meetings"),
            ("CROWD_2024 rollout Interview Request", "Releases"),
            ("thank you for your application - Venmo receipt", "Job Applications"),
            ("Venmo payment - action required", "Personal"),
            ("action required: renew newsletter subscription", "Action"),
        ],
    )
    def test_first_matching_rule_in_list_order_wins(self, subj: str, expected: str) -> None:
        assert organize.classify(subj, set(organize.FOLDERS)) == expected


class TestClassifyFallback:
    def test_job_applications_match_without_dest_or_fyi_folder_returns_none(self) -> None:
        assert organize.classify("thank you for your application", {"INBOX"}) is None

    def test_non_job_applications_match_without_dest_or_fyi_folder_returns_none(self) -> None:
        assert organize.classify("phishing attempt", {"INBOX"}) is None

    def test_non_job_applications_match_falls_back_to_fyi(self) -> None:
        assert organize.classify("phishing attempt", {"FYI", "INBOX"}) == "FYI"

    def test_job_applications_match_falls_back_to_fyi(self) -> None:
        assert organize.classify("thank you for your application", {"FYI", "INBOX"}) == "FYI"


class TestClassifyNonMatchingAndEdgeInputs:
    def test_unicode_subject_no_match_returns_none(self) -> None:
        assert organize.classify("日本語のテスト メール件名", set(organize.FOLDERS)) is None

    def test_unicode_sender_no_match_returns_none(self) -> None:
        assert (
            organize.classify("", set(organize.FOLDERS), sender="Üñíçødé Sénder Nàmé") is None
        )

    def test_none_subject_and_none_sender_returns_none(self) -> None:
        assert organize.classify(None, set(organize.FOLDERS), sender=None) is None  # type: ignore[arg-type]

    def test_empty_subject_and_empty_sender_returns_none(self) -> None:
        assert organize.classify("", set(organize.FOLDERS), sender="") is None

    def test_whitespace_only_subject_returns_none(self) -> None:
        assert organize.classify("   \n\t  ", set(organize.FOLDERS)) is None


class TestClassifyIsPureStringMatching:
    """classify() only ever does regex search on a string blob — it never
    builds or runs AppleScript, even when the input looks like an injection
    attempt against organize.py's *other* functions."""

    def test_quotes_and_backslashes_in_subject_still_match_and_no_applescript_call(self) -> None:
        with patch.object(organize, "run_as") as mock_run:
            result = organize.classify(
                'security alert: "SELECT * FROM users"; \\ drop table', set(organize.FOLDERS)
            )
        assert result == "Security"
        mock_run.assert_not_called()

    def test_quotes_and_backslashes_in_sender_still_match_and_no_applescript_call(self) -> None:
        with patch.object(organize, "run_as") as mock_run:
            result = organize.classify(
                "no match subject",
                set(organize.FOLDERS),
                sender='phishing "attacker" \\ payload',
            )
        assert result == "Security"
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# organize.fetch_subjects — output parsing edge cases
# ---------------------------------------------------------------------------


class TestFetchSubjectsEdgeCases:
    def test_subject_containing_unit_separator_splits_at_first_occurrence(self) -> None:
        with patch.object(organize, "run_as", return_value="1\tHel\x1flo\x1fBob\n"):
            rows = organize.fetch_subjects("Google", "INBOX", 10)
        # str.split(sep, 1) splits on the FIRST \x1f only — the rest, including
        # any further \x1f bytes, lands in sender verbatim.
        assert rows == [(1, "Hel", "lo\x1fBob")]

    def test_non_integer_index_row_skipped_others_kept(self) -> None:
        with patch.object(
            organize, "run_as", return_value="abc\tSubj1\n2\tSubj2\x1fSender2\n"
        ):
            rows = organize.fetch_subjects("Google", "INBOX", 10)
        assert rows == [(2, "Subj2", "Sender2")]

    def test_empty_run_as_output_returns_empty_list(self) -> None:
        with patch.object(organize, "run_as", return_value=""):
            rows = organize.fetch_subjects("Google", "INBOX", 10)
        assert rows == []

    def test_blank_and_tab_only_lines_skipped_among_valid_rows(self) -> None:
        with patch.object(
            organize, "run_as", return_value="\n\t\n1\tHello\x1fAlice\n\n2\tWorld\n"
        ):
            rows = organize.fetch_subjects("Google", "INBOX", 10)
        assert rows == [(1, "Hello", "Alice"), (2, "World", "")]

    def test_multiple_rows_without_unit_separator_each_default_to_empty_sender(self) -> None:
        with patch.object(organize, "run_as", return_value="1\tAlpha\n2\tBeta\n3\tGamma\n"):
            rows = organize.fetch_subjects("Google", "INBOX", 10)
        assert rows == [(1, "Alpha", ""), (2, "Beta", ""), (3, "Gamma", "")]


# ---------------------------------------------------------------------------
# organize.organize_inboxes — end-to-end with everything mocked
# ---------------------------------------------------------------------------


class TestOrganizeInboxesEdgeCases:
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
            fetch.return_value = [(1, "action required: sign form", "")]
            yield {
                "list_accts": list_accts,
                "list_boxes": list_boxes,
                "ensure": ensure,
                "fetch": fetch,
                "move": move,
            }

    def test_account_filter_matches_by_exact_name(self, mock_mail_ops) -> None:
        mock_mail_ops["list_accts"].return_value = [
            ("Google", "user@gmail.com"),
            ("Exchange", "work@corp.com"),
        ]
        code = organize.organize_inboxes(account="Google", out=io.StringIO())
        assert code == 0
        assert mock_mail_ops["list_boxes"].call_count == 1
        assert mock_mail_ops["list_boxes"].call_args[0][0] == "Google"

    def test_account_filter_matches_by_user_email_case_insensitive(self, mock_mail_ops) -> None:
        mock_mail_ops["list_accts"].return_value = [
            ("Google", "User@Gmail.com"),
            ("Exchange", "work@corp.com"),
        ]
        organize.organize_inboxes(account="user@gmail.com", out=io.StringIO())
        assert mock_mail_ops["list_boxes"].call_count == 1
        assert mock_mail_ops["list_boxes"].call_args[0][0] == "Google"

    def test_account_filter_matches_by_account_name_case_insensitive(self, mock_mail_ops) -> None:
        mock_mail_ops["list_accts"].return_value = [
            ("Google", "user@gmail.com"),
            ("Exchange", "work@corp.com"),
        ]
        organize.organize_inboxes(account="GOOGLE", out=io.StringIO())
        assert mock_mail_ops["list_boxes"].call_count == 1
        assert mock_mail_ops["list_boxes"].call_args[0][0] == "Google"

    def test_unknown_account_lists_known_accounts_in_stderr(self, capsys) -> None:
        with (
            patch.object(
                organize,
                "list_accounts",
                return_value=[("Google", "user@gmail.com"), ("Exchange", "work@corp.com")],
            ),
            patch.object(organize, "resolve_account_alias", side_effect=lambda x: x),
        ):
            code = organize.organize_inboxes(account="nope", out=io.StringIO())
        assert code == 2
        captured = capsys.readouterr()
        assert "FAIL: no account matching" in captured.err
        assert "Google|user@gmail.com" in captured.err
        assert "Exchange|work@corp.com" in captured.err

    def test_mailbox_exception_for_one_account_skips_but_others_continue(
        self, mock_mail_ops
    ) -> None:
        mock_mail_ops["list_accts"].return_value = [
            ("Broken", "broken@corp.com"),
            ("Google", "user@gmail.com"),
        ]
        mock_mail_ops["list_boxes"].side_effect = [
            RuntimeError("boom"),
            {"INBOX", "FYI", "Action"},
        ]
        buf = io.StringIO()
        code = organize.organize_inboxes(out=buf)
        assert code == 0
        output = buf.getvalue()
        assert "SKIP boxes: boom" in output
        assert "moved=1" in output
        mock_mail_ops["move"].assert_called_once()

    def test_more_than_three_move_failures_caps_printed_lines_at_three(
        self, mock_mail_ops
    ) -> None:
        mock_mail_ops["fetch"].return_value = [
            (i, f"action required item {i}", "") for i in range(1, 6)
        ]
        mock_mail_ops["move"].side_effect = RuntimeError("boom")
        buf = io.StringIO()
        code = organize.organize_inboxes(out=buf)
        assert code == 0
        output = buf.getvalue()
        assert output.count("FAIL move") == 3
        assert "moved=0" in output

    def test_moves_applied_in_descending_index_order(self, mock_mail_ops) -> None:
        mock_mail_ops["fetch"].return_value = [
            (1, "action required a", ""),
            (5, "action required b", ""),
            (3, "action required c", ""),
        ]
        organize.organize_inboxes(out=io.StringIO())
        called_indices = [call.args[2] for call in mock_mail_ops["move"].call_args_list]
        assert called_indices == [5, 3, 1]


# ---------------------------------------------------------------------------
# organize.resolve_account_alias — edge cases
# ---------------------------------------------------------------------------


class TestResolveAccountAliasEdgeCases:
    def test_empty_string_input_returns_unchanged(self) -> None:
        with patch.object(
            organize, "load_accounts_config", return_value={"aliases": {"google": "Google"}}
        ):
            assert organize.resolve_account_alias("") == ""

    def test_missing_accounts_json_propagates_file_not_found(self) -> None:
        with patch.object(
            organize, "load_accounts_config", side_effect=FileNotFoundError("no config")
        ):
            with pytest.raises(FileNotFoundError):
                organize.resolve_account_alias("google")


# ---------------------------------------------------------------------------
# batch.py — queue edge cases
# ---------------------------------------------------------------------------


class TestLoadQueueEdgeCases:
    def test_json_number_not_list_returns_empty(self, tmp_path: Path) -> None:
        q_file = tmp_path / "queue.json"
        q_file.write_text("42")
        assert batch.load_queue(q_file) == []


class TestEnqueueItemsEdgeCases:
    def test_duplicate_id_within_same_call_only_first_kept(self, tmp_path: Path) -> None:
        q_file = tmp_path / "queue.json"
        items = [
            {"id": "dup", "to": "a@x.com", "subject": "first"},
            {"id": "dup", "to": "b@x.com", "subject": "second"},
        ]
        added = batch.enqueue_items(items, q_file)
        assert added == 1
        loaded = batch.load_queue(q_file)
        assert len(loaded) == 1
        assert loaded[0]["to"] == "a@x.com"

    def test_auto_generated_ids_are_unique_within_same_call(self, tmp_path: Path) -> None:
        q_file = tmp_path / "queue.json"
        items = [{"to": "a@x.com"}, {"to": "a@x.com"}]
        with (
            patch("imail.batch.time.time", return_value=1000.0),
            patch("imail.batch.random.randint", side_effect=[111, 222]),
        ):
            added = batch.enqueue_items(items, q_file)
        assert added == 2
        loaded = batch.load_queue(q_file)
        assert loaded[0]["id"] != loaded[1]["id"]


class TestClearQueueEdgeCases:
    def test_status_filter_matching_nothing_returns_zero_and_untouched(
        self, tmp_path: Path
    ) -> None:
        q_file = tmp_path / "queue.json"
        items = [{"id": "1", "status": "pending"}, {"id": "2", "status": "sent"}]
        batch.save_queue(items, q_file)
        cleared = batch.clear_queue(q_file, status_filter="failed")
        assert cleared == 0
        assert batch.load_queue(q_file) == items


class TestGetQueueSummaryEdgeCases:
    def test_counts_multiple_unknown_statuses_separately(self, tmp_path: Path) -> None:
        q_file = tmp_path / "queue.json"
        items = [
            {"id": "1", "status": "archived"},
            {"id": "2", "status": "archived"},
            {"id": "3", "status": "spam"},
        ]
        batch.save_queue(items, q_file)
        summary = batch.get_queue_summary(q_file)
        assert summary["archived"] == 2
        assert summary["spam"] == 1
        assert summary["pending"] == 0


class TestRunBatchDispatchLimitEdgeCases:
    def test_limit_zero_means_no_limit(self, tmp_path: Path) -> None:
        q_file = tmp_path / "queue.json"
        items = [
            {
                "id": str(i),
                "to": f"{i}@x.com",
                "subject": "s",
                "body": "b",
                "from_addr": "f@x.com",
                "status": "pending",
            }
            for i in range(3)
        ]
        batch.save_queue(items, q_file)
        with patch("imail.mail.send_message", return_value="OK"):
            stats = batch.run_batch_dispatch(
                queue_path=q_file, limit=0, min_delay=0.0, max_delay=0.0
            )
        assert stats["processed"] == 3

    def test_limit_none_explicit_means_no_limit(self, tmp_path: Path) -> None:
        q_file = tmp_path / "queue.json"
        items = [
            {
                "id": str(i),
                "to": f"{i}@x.com",
                "subject": "s",
                "body": "b",
                "from_addr": "f@x.com",
                "status": "pending",
            }
            for i in range(3)
        ]
        batch.save_queue(items, q_file)
        with patch("imail.mail.send_message", return_value="OK"):
            stats = batch.run_batch_dispatch(
                queue_path=q_file, limit=None, min_delay=0.0, max_delay=0.0
            )
        assert stats["processed"] == 3


class TestRunBatchDispatchDryRunEdgeCases:
    def test_dry_run_never_calls_send_message(self, tmp_path: Path) -> None:
        q_file = tmp_path / "queue.json"
        items = [
            {
                "id": "1",
                "to": "a@x.com",
                "subject": "s",
                "body": "b",
                "from_addr": "f@x.com",
                "status": "pending",
            }
        ]
        batch.save_queue(items, q_file)
        with patch("imail.mail.send_message") as mock_send:
            batch.run_batch_dispatch(
                queue_path=q_file, dry_run=True, min_delay=0.0, max_delay=0.0
            )
        mock_send.assert_not_called()


class TestRunBatchDispatchFailureContinuation:
    def test_first_item_fails_second_succeeds_processing_continues(
        self, tmp_path: Path
    ) -> None:
        q_file = tmp_path / "queue.json"
        items = [
            {
                "id": "1",
                "to": "bad@x.com",
                "subject": "s1",
                "body": "b1",
                "from_addr": "f@x.com",
                "status": "pending",
            },
            {
                "id": "2",
                "to": "good@x.com",
                "subject": "s2",
                "body": "b2",
                "from_addr": "f@x.com",
                "status": "pending",
            },
        ]
        batch.save_queue(items, q_file)

        def mock_send(**kwargs):
            if kwargs["to"] == "bad@x.com":
                raise RuntimeError("first item boom")
            return "OK"

        with patch("imail.mail.send_message", side_effect=mock_send):
            stats = batch.run_batch_dispatch(queue_path=q_file, min_delay=0.0, max_delay=0.0)

        assert stats == {"processed": 2, "sent": 1, "failed": 1}
        final_queue = batch.load_queue(q_file)
        assert final_queue[0]["status"] == "failed"
        assert "first item boom" in final_queue[0]["error"]
        assert final_queue[1]["status"] == "sent"


class TestRunBatchDispatchProgressCallback:
    def test_progress_callback_args_dry_run(self, tmp_path: Path) -> None:
        q_file = tmp_path / "queue.json"
        items = [
            {
                "id": "1",
                "to": "a@x.com",
                "subject": "s",
                "body": "b",
                "from_addr": "f@x.com",
                "status": "pending",
            },
            {
                "id": "2",
                "to": "b@x.com",
                "subject": "s",
                "body": "b",
                "from_addr": "f@x.com",
                "status": "pending",
            },
        ]
        batch.save_queue(items, q_file)
        calls: list[tuple[str, int, int]] = []
        batch.run_batch_dispatch(
            queue_path=q_file,
            dry_run=True,
            min_delay=0.0,
            max_delay=0.0,
            progress_callback=lambda item, step, total: calls.append(
                (item["id"], step, total)
            ),
        )
        assert calls == [("1", 1, 2), ("2", 2, 2)]

    def test_progress_callback_args_on_failed_item(self, tmp_path: Path) -> None:
        q_file = tmp_path / "queue.json"
        items = [
            {
                "id": "1",
                "to": "bad@x.com",
                "subject": "s",
                "body": "b",
                "from_addr": "f@x.com",
                "status": "pending",
            }
        ]
        batch.save_queue(items, q_file)
        calls: list[tuple[str, int, int]] = []
        with patch("imail.mail.send_message", side_effect=RuntimeError("nope")):
            batch.run_batch_dispatch(
                queue_path=q_file,
                min_delay=0.0,
                max_delay=0.0,
                progress_callback=lambda item, step, total: calls.append(
                    (item["status"], step, total)
                ),
            )
        assert calls == [("failed", 1, 1)]


class TestRunBatchDispatchSleepJitter:
    def test_sleep_and_jitter_not_called_after_last_item(self, tmp_path: Path) -> None:
        q_file = tmp_path / "queue.json"
        items = [
            {
                "id": str(i),
                "to": f"{i}@x.com",
                "subject": "s",
                "body": "b",
                "from_addr": "f@x.com",
                "status": "pending",
            }
            for i in range(3)
        ]
        batch.save_queue(items, q_file)
        with (
            patch("imail.mail.send_message", return_value="OK"),
            patch("imail.batch.time.sleep") as mock_sleep,
            patch("imail.batch.random.uniform", return_value=0.0) as mock_uniform,
        ):
            batch.run_batch_dispatch(queue_path=q_file, min_delay=1.0, max_delay=2.0)
        # 3 items -> sleeps between item 1->2 and 2->3, never after the last one.
        assert mock_uniform.call_count == 2
        assert mock_sleep.call_count == 2


# ---------------------------------------------------------------------------
# agent.py — schema/guide edge cases
# ---------------------------------------------------------------------------


class TestBuildSchemaEdgeCases:
    def test_missing_walls_key_defaults_to_empty_structures(self) -> None:
        with patch.object(agent, "load_accounts_config", return_value={}):
            schema = agent.build_schema()
        assert schema["walls"]["work"]["accounts"] == []
        assert schema["walls"]["work"]["emails"] == []
        assert schema["walls"]["personal"]["accounts"] == []
        assert schema["walls"]["personal"]["emails"] == []
        assert schema["walls"]["personal"]["primary_google"] == ""

    def test_partial_walls_missing_primary_google(self) -> None:
        with patch.object(
            agent,
            "load_accounts_config",
            return_value={"walls": {"personal": {"accounts": ["Google"], "emails": ["a@b.com"]}}},
        ):
            schema = agent.build_schema()
        assert schema["walls"]["personal"]["accounts"] == ["Google"]
        assert schema["walls"]["personal"]["emails"] == ["a@b.com"]
        assert schema["walls"]["personal"]["primary_google"] == ""


class TestGuideTextEdgeCases:
    def test_missing_rules_key_no_crash_no_bullets(self) -> None:
        with patch.object(agent, "load_accounts_config", return_value={"walls": {}}):
            text = agent.guide_text()
        assert "•" not in text.split("Rules:")[-1]

    def test_empty_rules_list_no_bullets(self) -> None:
        with patch.object(
            agent, "load_accounts_config", return_value={"walls": {}, "rules": []}
        ):
            text = agent.guide_text()
        assert "•" not in text.split("Rules:")[-1]

    def test_unicode_wall_emails_appear_correctly(self) -> None:
        config = {
            "walls": {
                "work": {"accounts": [], "emails": ["üser@wörk.example"]},
                "personal": {
                    "accounts": [],
                    "emails": ["pérsönal@exämple.com"],
                    "primary_google": "",
                },
            },
            "rules": [],
        }
        with patch.object(agent, "load_accounts_config", return_value=config):
            text = agent.guide_text()
        assert "üser@wörk.example" in text
        assert "pérsönal@exämple.com" in text


class TestSchemaJsonEdgeCases:
    def test_valid_json_with_unicode_walls(self) -> None:
        config = {
            "walls": {
                "work": {"accounts": ["Wörk Account"], "emails": ["üser@wörk.example"]},
                "personal": {"accounts": [], "emails": [], "primary_google": ""},
            }
        }
        with patch.object(agent, "load_accounts_config", return_value=config):
            data = json.loads(agent.schema_json())
        assert data["walls"]["work"]["accounts"] == ["Wörk Account"]
        assert data["walls"]["work"]["emails"] == ["üser@wörk.example"]
