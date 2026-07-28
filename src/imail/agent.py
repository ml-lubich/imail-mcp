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
                        "required": False,
                        "help": "Message body string or path to body file",
                    },
                    {
                        "name": "body-file",
                        "type": "string",
                        "required": False,
                        "help": "Path to body file (reads text file content)",
                    },
                    {
                        "name": "cc",
                        "type": "string",
                        "required": False,
                        "help": "Optional CC address",
                    },
                    {
                        "name": "attach",
                        "type": "string",
                        "required": False,
                        "help": "Path to file attachment (repeatable)",
                    },
                    {
                        "name": "markdown",
                        "type": "boolean",
                        "required": False,
                        "help": "Parse body as Markdown and format as rich HTML",
                    },
                    {
                        "name": "zip",
                        "type": "boolean",
                        "required": False,
                        "help": "Bundle attachments into a single .zip archive",
                    },
                    {
                        "name": "open",
                        "type": "boolean",
                        "required": False,
                        "help": "Open native WebKit HTML draft in Mail.app for review before sending",
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
        "  imail send --from michaelle.lubich@gmail.com --to recipient@domain.com \\",
        '    --subject "Subject" --body-file "/path/to/letter.md" -m -a "/path/to/resume.pdf"',
        "",
        "Agent Instructions for Sending Email:",
        "  1. Wall Check: Verify sender account matches work vs personal wall rules.",
        "  2. Content Formatting: Use -m / --markdown for rich HTML rendering (uses modern sans-serif typography).",
        "  3. Attachments: Pass -a / --attach for files (e.g. resumes, PDFs). Use --zip to bundle multiple attachments.",
        "  4. Draft Review: Use -o / --open to launch a native WebKit draft in Mail.app for user review.",
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
