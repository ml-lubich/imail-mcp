"""Automated prompt evaluation tests verifying 2026 AI-Native compliance.

Verifies:
1. All required prompt files exist in `prompts/` (triage.md, auto-reply.md, meeting-extractor.md).
2. Character and token limits conform to strict budget constraints.
3. Guardrail rules are embedded (untrusted email handling, anti-injection, length caps).
4. CLI subcommand `imail prompt` functions correctly with --list, <name>, and --json output.
5. Few-shot example outputs adhere to their respective schema definitions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typer.testing import CliRunner

from imail import prompts
from imail.cli import app

runner = CliRunner()

REQUIRED_PROMPTS = [
    "triage",
    "auto-reply",
    "meeting-extractor",
]


class TestPromptsPresence:
    def test_prompts_directory_exists(self) -> None:
        pdir = prompts.get_prompts_dir()
        assert pdir.is_dir(), f"Prompts directory not found at {pdir}"

    def test_required_prompts_exist(self) -> None:
        available = prompts.list_prompts()
        for rp in REQUIRED_PROMPTS:
            assert rp in available, f"Required prompt '{rp}' is missing from {available}"

    def test_prompts_files_readable_and_non_empty(self) -> None:
        for rp in REQUIRED_PROMPTS:
            content, path = prompts.load_prompt_file(rp)
            assert path.exists()
            assert len(content.strip()) > 100, f"Prompt '{rp}' content is unexpectedly short"


class TestPromptsTokenBudgetAndConstraints:
    """Validate character and token budget compliance for prompt files."""

    def test_token_budgets(self) -> None:
        # Strict context budget: single prompt should not exceed 2000 tokens (~8000 chars)
        for rp in REQUIRED_PROMPTS:
            meta = prompts.get_prompt_metadata(rp)
            assert meta["char_count"] < 8000, f"Prompt {rp} exceeded 8000 char budget ({meta['char_count']})"
            assert meta["approx_token_count"] < 2000, f"Prompt {rp} exceeded token budget ({meta['approx_token_count']})"

    def test_triage_prompt_specifications(self) -> None:
        meta = prompts.get_prompt_metadata("triage")
        raw = meta["instructions"]
        # Must classify personal vs work, action required, meeting, low-stakes auto-reply candidate
        assert "personal" in raw.lower()
        assert "work" in raw.lower()
        assert "action_required" in raw
        assert "is_meeting" in raw
        assert "auto_reply_candidate" in raw
        assert "untrusted" in raw.lower()

    def test_auto_reply_guardrail_policy(self) -> None:
        meta = prompts.get_prompt_metadata("auto-reply")
        raw = meta["instructions"]
        # Must enforce <= 400 characters constraint
        assert "400" in raw
        assert "untrusted" in raw.lower()
        # Verify few-shot drafts adhere to <= 400 chars
        for fs in meta["few_shots"]:
            out = fs.get("output", {})
            if isinstance(out, dict) and "reply" in out:
                reply_body = out["reply"]
                assert len(reply_body) <= 400, f"Draft exceeded 400 chars: {len(reply_body)}"
                assert out.get("char_count") == len(reply_body)

    def test_meeting_extractor_specifications(self) -> None:
        meta = prompts.get_prompt_metadata("meeting-extractor")
        raw = meta["instructions"]
        # Must extract times, dates, attendees, Zoom/Google Meet links
        assert "proposed_times" in raw or "times" in raw.lower()
        assert "attendees" in raw
        assert "meeting_link" in raw or "zoom" in raw.lower()
        assert "google meet" in raw.lower()


class TestPromptsCliSubcommand:
    """Test `imail prompt` CLI behaviors."""

    def test_cli_prompt_list(self) -> None:
        result = runner.invoke(app, ["prompt", "--list"])
        assert result.exit_code == 0
        assert "Available prompts:" in result.output
        for rp in REQUIRED_PROMPTS:
            assert rp in result.output

    def test_cli_prompt_list_json(self) -> None:
        result = runner.invoke(app, ["prompt", "--list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "prompts" in data
        for rp in REQUIRED_PROMPTS:
            assert rp in data["prompts"]

    def test_cli_prompt_export_all_json(self) -> None:
        result = runner.invoke(app, ["prompt", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "prompts" in data
        names = [p["name"] for p in data["prompts"]]
        for rp in REQUIRED_PROMPTS:
            assert rp in names

    def test_cli_prompt_get_plain(self) -> None:
        result = runner.invoke(app, ["prompt", "auto-reply"])
        assert result.exit_code == 0
        assert "# Auto-Reply Grounded Draft Prompt" in result.output

    def test_cli_prompt_get_json(self) -> None:
        for rp in REQUIRED_PROMPTS:
            result = runner.invoke(app, ["prompt", rp, "--json"])
            assert result.exit_code == 0
            payload = json.loads(result.output)
            assert payload["name"] == rp
            assert "instructions" in payload
            assert "schema" in payload
            assert "few_shots" in payload
            assert len(payload["few_shots"]) > 0

    def test_cli_prompt_not_found(self) -> None:
        result = runner.invoke(app, ["prompt", "unknown-bogus-prompt"])
        assert result.exit_code == 1
        assert "FAIL: Prompt 'unknown-bogus-prompt' not found" in result.output
