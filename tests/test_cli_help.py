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
    "autodraft",
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
        assert "doctor" in result.output and "agent" in result.output
        assert "--install-completion" not in result.output
        assert "--show-completion" not in result.output


def test_root_version_shortcut() -> None:
    result = runner.invoke(app, ["-V"])
    assert result.exit_code == 0
    assert "imail" in result.output.lower()
    assert "--install-completion" not in runner.invoke(app, ["-h"]).output

def test_imsg_style_help_and_root_options() -> None:
    result = runner.invoke(app, ["help"])
    assert result.exit_code == 0
    assert "imail <command> -h" in result.output
    assert "Examples:" in result.output

    result = runner.invoke(app, ["help", "list"])
    assert result.exit_code == 0
    assert "imail list -h" in result.output

    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip()

    result = runner.invoke(app, ["list", "-h"])
    assert result.exit_code == 0
    assert "--json" in result.output and "-j" in result.output
    assert "--limit" in result.output and "-n" in result.output


def test_root_json_and_quiet_options() -> None:
    result = runner.invoke(app, ["--json", "version"])
    assert result.exit_code == 0
    assert result.output.strip()

    result = runner.invoke(app, ["-j", "version"])
    assert result.exit_code == 0
    assert result.output.strip()

    result = runner.invoke(app, ["--quiet", "version"])
    assert result.exit_code == 0
    assert result.output.strip()


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
