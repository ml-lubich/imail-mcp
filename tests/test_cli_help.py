"""CLI help and agent schema tests."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from imail.cli import app

runner = CliRunner()

TOP_LEVEL_COMMANDS = [
    "doctor",
    "accounts",
    "walls",
    "list",
    "organize",
    "send",
    "version",
]

AGENT_COMMANDS = [
    "schema",
    "guide",
]


def test_main_help_variants() -> None:
    for args in (["--help"], ["-h"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        assert "Apple Mail.app CLI" in result.output


def test_subcommand_help() -> None:
    for cmd in TOP_LEVEL_COMMANDS:
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code == 0, f"{cmd}: {result.output}"
        result = runner.invoke(app, [cmd, "-h"])
        assert result.exit_code == 0, f"{cmd} -h: {result.output}"


def test_agent_subcommand_help() -> None:
    for sub in AGENT_COMMANDS:
        result = runner.invoke(app, ["agent", sub, "--help"])
        assert result.exit_code == 0, f"agent {sub}: {result.output}"
        result = runner.invoke(app, ["agent", sub, "-h"])
        assert result.exit_code == 0, f"agent {sub} -h: {result.output}"


def test_agent_schema_valid_json() -> None:
    result = runner.invoke(app, ["agent", "schema"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["tool"] == "imail"
    assert "version" in data
    assert "walls" in data
    assert isinstance(data["commands"], list)
    assert len(data["commands"]) > 0
    for cmd in data["commands"]:
        assert "name" in cmd
        assert "help" in cmd
        assert "params" in cmd
