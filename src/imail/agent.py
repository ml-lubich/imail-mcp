"""Agent-facing schema and guide for imail CLI."""

from __future__ import annotations

import json
from typing import Any

from imail import __version__
from imail.mail import load_accounts_config


def build_schema() -> dict[str, Any]:
    config = load_accounts_config()
    walls = config.get("walls", {})
    return {
        "version": __version__,
        "tool": "imail",
        "walls": {
            "work": {
                "accounts": walls.get("work", {}).get("accounts", []),
                "emails": walls.get("work", {}).get("emails", []),
            },
            "personal": {
                "accounts": walls.get("personal", {}).get("accounts", []),
                "emails": walls.get("personal", {}).get("emails", []),
                "primary_google": walls.get("personal", {}).get("primary_google", ""),
            },
        },
        "commands": [
            {
                "name": "doctor",
                "help": "Verify Mail.app is reachable via Automation",
                "params": [],
            },
            {
                "name": "accounts",
                "help": "List Mail.app accounts (name and email)",
                "params": [],
            },
            {
                "name": "walls",
                "help": "Print work vs personal account walls from accounts.json",
                "params": [],
            },
            {
                "name": "list",
                "help": "List messages from inbox or account mailbox",
                "params": [
                    {
                        "name": "account",
                        "type": "string",
                        "required": False,
                        "help": "Account name or email",
                    },
                    {
                        "name": "mailbox",
                        "type": "string",
                        "required": False,
                        "help": "Mailbox name (default INBOX)",
                    },
                    {
                        "name": "limit",
                        "type": "integer",
                        "required": False,
                        "help": "Max messages (default 20)",
                    },
                    {
                        "name": "json",
                        "type": "boolean",
                        "required": False,
                        "help": "Output JSON instead of TSV",
                    },
                ],
            },
            {
                "name": "organize",
                "help": "Classify and MOVE inbox messages into folders (never delete)",
                "params": [
                    {
                        "name": "account",
                        "type": "string",
                        "required": False,
                        "help": "Account alias: google, polaris, metropol, lupfr, etc.",
                    },
                    {
                        "name": "limit",
                        "type": "integer",
                        "required": False,
                        "help": "Max messages per inbox (default 200)",
                    },
                ],
            },
            {
                "name": "send",
                "help": "Send email via Mail.app (requires --from on correct wall)",
                "params": [
                    {
                        "name": "from",
                        "type": "string",
                        "required": True,
                        "help": "Sender email matching account wall",
                    },
                    {
                        "name": "to",
                        "type": "string",
                        "required": True,
                        "help": "Recipient address",
                    },
                    {
                        "name": "subject",
                        "type": "string",
                        "required": True,
                        "help": "Message subject",
                    },
                    {
                        "name": "body",
                        "type": "string",
                        "required": True,
                        "help": "Message body",
                    },
                    {
                        "name": "cc",
                        "type": "string",
                        "required": False,
                        "help": "Optional CC address",
                    },
                ],
            },
            {
                "name": "version",
                "help": "Print package version",
                "params": [],
            },
            {
                "name": "agent schema",
                "help": "Print JSON schema of all commands and walls",
                "params": [],
            },
            {
                "name": "agent guide",
                "help": "Print human/agent usage guide",
                "params": [],
            },
        ],
    }


def schema_json() -> str:
    return json.dumps(build_schema(), indent=2)


def guide_text() -> str:
    config = load_accounts_config()
    rules = config.get("rules", [])
    lines = [
        "imail — Apple Mail.app CLI",
        "",
        "Prefer CLI over MCP for token efficiency.",
        "HARD RULE: never mix Polaris/work with personal Gmail walls.",
        "",
        "Quick start:",
        "  imail doctor",
        "  imail walls",
        "  imail list --limit 10",
        "  imail organize --account polaris --limit 100",
        "  imail send --from mlubich@polariswireless.com --to a@b.com \\",
        '    --subject "Hi" --body "Hello"',
        "",
        "Agent introspection:",
        "  imail agent schema   # JSON command catalog",
        "  imail agent guide    # this text",
        "",
        "Rules:",
    ]
    for rule in rules:
        lines.append(f"  • {rule}")
    return "\n".join(lines)
