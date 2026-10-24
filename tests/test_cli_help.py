"""CLI help and agent schema tests."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from conftest import plain_output

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
        assert result.exit_code == 0, plain_output(result.output)
        assert "Apple Mail.app CLI" in plain_output(result.output)
        assert "doctor" in plain_output(result.output) and "agent" in plain_output(result.output)
        assert "--install-completion" not in plain_output(result.output)
        assert "--show-completion" not in plain_output(result.output)


def test_root_version_shortcut() -> None:
    result = runner.invoke(app, ["-V"])
    assert result.exit_code == 0
    assert "imail" in plain_output(result.output).lower()
    assert "--install-completion" not in runner.invoke(app, ["-h"]).output

def test_imsg_style_help_and_root_options() -> None:
    result = runner.invoke(app, ["help"])
    assert result.exit_code == 0
    assert "imail <command> -h" in plain_output(result.output)
    assert "Examples:" in plain_output(result.output)

    result = runner.invoke(app, ["help", "list"])
    assert result.exit_code == 0
    assert "imail list -h" in plain_output(result.output)

    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert plain_output(result.output).strip()

    result = runner.invoke(app, ["list", "-h"])
    assert result.exit_code == 0
    assert "--json" in plain_output(result.output) and "-j" in plain_output(result.output)
    assert "--limit" in plain_output(result.output) and "-n" in plain_output(result.output)


def test_root_json_and_quiet_options() -> None:
    result = runner.invoke(app, ["--json", "version"])
    assert result.exit_code == 0
    assert plain_output(result.output).strip()

    result = runner.invoke(app, ["-j", "version"])
    assert result.exit_code == 0
    assert plain_output(result.output).strip()

    result = runner.invoke(app, ["--quiet", "version"])
    assert result.exit_code == 0
    assert plain_output(result.output).strip()


def test_subcommand_help() -> None:
    for cmd in TOP_LEVEL_COMMANDS:
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code == 0, f"{cmd}: {plain_output(result.output)}"
        result = runner.invoke(app, [cmd, "-h"])
        assert result.exit_code == 0, f"{cmd} -h: {plain_output(result.output)}"


def test_agent_subcommand_help() -> None:
    for sub in AGENT_COMMANDS:
        result = runner.invoke(app, ["agent", sub, "--help"])
        assert result.exit_code == 0, f"agent {sub}: {plain_output(result.output)}"
        result = runner.invoke(app, ["agent", sub, "-h"])
        assert result.exit_code == 0, f"agent {sub} -h: {plain_output(result.output)}"


def test_agent_schema_valid_json() -> None:
    result = runner.invoke(app, ["agent", "schema"])
    assert result.exit_code == 0, plain_output(result.output)
    data = json.loads(plain_output(result.output))
    assert data["tool"] == "imail"
    assert "version" in data
    assert "walls" in data
    assert isinstance(data["commands"], list)
    assert len(data["commands"]) > 0
    for cmd in data["commands"]:
        assert "name" in cmd
        assert "help" in cmd
        assert "params" in cmd
