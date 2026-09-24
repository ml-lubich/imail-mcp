"""Tests for imail.batch queue and dispatching."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from imail import batch
from imail.cli import app

runner = CliRunner()


class TestBatchQueue:
    def test_load_empty_or_missing_queue(self, tmp_path: Path) -> None:
        q_file = tmp_path / "sub" / "queue.json"
        assert batch.load_queue(q_file) == []

    def test_load_corrupt_queue(self, tmp_path: Path) -> None:
        q_file = tmp_path / "queue.json"
        q_file.write_text("invalid json")
        assert batch.load_queue(q_file) == []

    def test_load_non_list_queue(self, tmp_path: Path) -> None:
        q_file = tmp_path / "queue.json"
        q_file.write_text('{"not": "a list"}')
        assert batch.load_queue(q_file) == []

    def test_enqueue_items(self, tmp_path: Path) -> None:
        q_file = tmp_path / "queue.json"
        items = [
            {"to": "alice@example.com", "subject": "Hi", "body": "Body 1"},
            {"to": "bob@example.com", "subject": "Hello", "body": "Body 2", "id": "custom-id-1"},
        ]
        added = batch.enqueue_items(items, q_file)
        assert added == 2

        # Adding same ID should not duplicate
        added_again = batch.enqueue_items([{"id": "custom-id-1", "to": "bob@example.com"}], q_file)
        assert added_again == 0

        loaded = batch.load_queue(q_file)
        assert len(loaded) == 2
        assert loaded[1]["id"] == "custom-id-1"
        assert loaded[1]["status"] == "pending"

    def test_get_queue_summary(self, tmp_path: Path) -> None:
        q_file = tmp_path / "queue.json"
        items = [
            {"id": "1", "status": "pending"},
            {"id": "2", "status": "sent"},
            {"id": "3", "status": "failed"},
            {"id": "4", "status": "custom_other"},
        ]
        batch.save_queue(items, q_file)
        summary = batch.get_queue_summary(q_file)
        assert summary["total"] == 4
        assert summary["pending"] == 1
        assert summary["sent"] == 1
        assert summary["failed"] == 1
        assert summary["custom_other"] == 1

    def test_clear_queue(self, tmp_path: Path) -> None:
        q_file = tmp_path / "queue.json"
        items = [
            {"id": "1", "status": "pending"},
            {"id": "2", "status": "sent"},
        ]
        batch.save_queue(items, q_file)

        # Clear with filter
        cleared_sent = batch.clear_queue(q_file, status_filter="sent")
        assert cleared_sent == 1
        remaining = batch.load_queue(q_file)
        assert len(remaining) == 1
        assert remaining[0]["id"] == "1"

        # Clear all
        cleared_all = batch.clear_queue(q_file)
        assert cleared_all == 1
        assert batch.load_queue(q_file) == []


class TestBatchDispatch:
    def test_run_batch_dispatch_dry_run(self, tmp_path: Path) -> None:
        q_file = tmp_path / "queue.json"
        items = [
            {"id": "1", "to": "a@test.com", "subject": "s1", "body": "b1", "from_addr": "f@test.com", "status": "pending"},
            {"id": "2", "to": "b@test.com", "subject": "s2", "body": "b2", "from_addr": "f@test.com", "status": "pending"},
        ]
        batch.save_queue(items, q_file)

        progress_reports = []
        stats = batch.run_batch_dispatch(
            queue_path=q_file,
            min_delay=0.01,
            max_delay=0.02,
            dry_run=True,
            progress_callback=lambda item, step, total: progress_reports.append((step, total, item["status"])),
        )

        assert stats["processed"] == 2
        assert stats["sent"] == 2
        assert stats["failed"] == 0
        assert len(progress_reports) == 2
        assert progress_reports[0] == (1, 2, "dry_run")

    def test_run_batch_dispatch_real_success_and_fail(self, tmp_path: Path) -> None:
        q_file = tmp_path / "queue.json"
        items = [
            {"id": "1", "to": "good@test.com", "subject": "s1", "body": "b1", "from_addr": "f@test.com", "status": "pending"},
            {"id": "2", "to": "bad@test.com", "subject": "s2", "body": "b2", "from_addr": "f@test.com", "status": "pending"},
        ]
        batch.save_queue(items, q_file)

        def mock_send(**kwargs):
            if kwargs["to"] == "bad@test.com":
                raise RuntimeError("SMTP fail")
            return "OK"

        with patch("imail.mail.send_message", side_effect=mock_send):
            stats = batch.run_batch_dispatch(
                queue_path=q_file,
                min_delay=0.01,
                max_delay=0.02,
            )

        assert stats["processed"] == 2
        assert stats["sent"] == 1
        assert stats["failed"] == 1

        final_queue = batch.load_queue(q_file)
        assert final_queue[0]["status"] == "sent"
        assert final_queue[1]["status"] == "failed"
        assert "SMTP fail" in final_queue[1]["error"]

    def test_run_batch_dispatch_with_limit(self, tmp_path: Path) -> None:
        q_file = tmp_path / "queue.json"
        items = [
            {"id": "1", "to": "a@test.com", "subject": "s1", "body": "b1", "from_addr": "f@test.com", "status": "pending"},
            {"id": "2", "to": "b@test.com", "subject": "s2", "body": "b2", "from_addr": "f@test.com", "status": "pending"},
        ]
        batch.save_queue(items, q_file)

        with patch("imail.mail.send_message", return_value="OK"):
            stats = batch.run_batch_dispatch(
                queue_path=q_file,
                limit=1,
                min_delay=0.01,
                max_delay=0.02,
            )

        assert stats["processed"] == 1
        assert stats["sent"] == 1
        final_queue = batch.load_queue(q_file)
        assert final_queue[0]["status"] == "sent"
        assert final_queue[1]["status"] == "pending"


class TestBatchCLI:
    def test_status_empty_queue(self, tmp_path: Path) -> None:
        q_file = tmp_path / "empty_queue.json"
        result = runner.invoke(app, ["status", "--queue-file", str(q_file)])
        assert result.exit_code == 0
        assert "Total: 0" in result.output

    def test_status_with_items(self, tmp_path: Path) -> None:
        q_file = tmp_path / "q.json"
        batch.save_queue([{"id": "1", "to": "test@domain.com", "subject": "Review", "status": "pending"}], q_file)
        result = runner.invoke(app, ["status", "--queue-file", str(q_file)])
        assert result.exit_code == 0
        assert "Total: 1 | Pending: 1" in result.output
        assert "test@domain.com" in result.output

    def test_batch_clear(self, tmp_path: Path) -> None:
        q_file = tmp_path / "q.json"
        batch.save_queue([{"id": "1", "status": "pending"}], q_file)
        result = runner.invoke(app, ["batch", "--clear", "--queue-file", str(q_file)])
        assert result.exit_code == 0
        assert "Cleared 1 items" in result.output

    def test_batch_file_not_found(self, tmp_path: Path) -> None:
        q_file = tmp_path / "q.json"
        result = runner.invoke(app, ["batch", "--file", str(tmp_path / "missing.json"), "--queue-file", str(q_file)])
        assert result.exit_code == 1
        assert "FAIL: Batch file not found" in result.output

    def test_batch_file_invalid_json(self, tmp_path: Path) -> None:
        b_file = tmp_path / "bad.json"
        b_file.write_text("{bad")
        q_file = tmp_path / "q.json"
        result = runner.invoke(app, ["batch", "--file", str(b_file), "--queue-file", str(q_file)])
        assert result.exit_code == 1
        assert "FAIL: Error parsing batch file" in result.output

    def test_batch_file_not_a_list(self, tmp_path: Path) -> None:
        b_file = tmp_path / "dict.json"
        b_file.write_text('{"key": "value"}')
        q_file = tmp_path / "q.json"
        result = runner.invoke(app, ["batch", "--file", str(b_file), "--queue-file", str(q_file)])
        assert result.exit_code == 1
        assert "FAIL: Batch file must contain a JSON array" in result.output

    def test_batch_enqueue_and_run(self, tmp_path: Path) -> None:
        b_file = tmp_path / "batch.json"
        b_file.write_text(json.dumps([{"to": "target@domain.com", "subject": "Hey", "body": "test", "from_addr": "me@domain.com"}]))
        q_file = tmp_path / "q.json"

        with patch("imail.mail.send_message", return_value="OK"):
            result = runner.invoke(app, [
                "batch",
                "--file", str(b_file),
                "--run",
                "--queue-file", str(q_file),
                "--min-delay", "0.01",
                "--max-delay", "0.02",
            ])

        assert result.exit_code == 0
        assert "Enqueued 1 items" in result.output
        assert "Batch completed: 1 processed, 1 sent" in result.output

    def test_batch_run_empty_queue(self, tmp_path: Path) -> None:
        q_file = tmp_path / "empty.json"
        result = runner.invoke(app, ["batch", "--run", "--queue-file", str(q_file)])
        assert result.exit_code == 0
        assert "No pending items in queue to process." in result.output
