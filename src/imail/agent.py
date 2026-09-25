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
                        "help": "Account alias from accounts.json `aliases`, or a Mail.app account name.",
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
                "name": "autodraft",
                "help": "Scan personal inboxes, draft replies, auto-send only low-stakes follow-ups",
                "params": [
                    {
                        "name": "account",
                        "type": "string",
                        "required": False,
                        "help": "Account email (defaults to all personal walls)",
                    },
                    {
                        "name": "limit",
                        "type": "integer",
                        "required": False,
                        "help": "Max messages per inbox (default 15)",
                    },
                    {
                        "name": "dry-run",
                        "type": "boolean",
                        "required": False,
                        "help": "Preview decisions without drafting or sending",
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
                    {
                        "name": "humanize",
                        "type": "boolean",
                        "required": False,
                        "help": "Subtly humanize body text (strip emojis, 5-10% natural typing touch, inspired by blader/humanizer)",
                    },
                ],
            },
            {
                "name": "status",
                "help": "Show status of queued and sent batch emails",
                "params": [
                    {
                        "name": "queue-file",
                        "type": "string",
                        "required": False,
                        "help": "Path to custom queue file",
                    }
                ],
            },
            {
                "name": "batch",
                "help": "Queue, manage, and dispatch batch emails with randomized intervals",
                "params": [
                    {
                        "name": "file",
                        "type": "string",
                        "required": False,
                        "help": "JSON file containing array of email jobs to queue",
                    },
                    {
                        "name": "run",
                        "type": "boolean",
                        "required": False,
                        "help": "Dispatch pending queued jobs immediately",
                    },
                    {
                        "name": "limit",
                        "type": "integer",
                        "required": False,
                        "help": "Max jobs to process in this run",
                    },
                    {
                        "name": "min-delay",
                        "type": "number",
                        "required": False,
                        "help": "Minimum randomized jitter delay in seconds",
                    },
                    {
                        "name": "max-delay",
                        "type": "number",
                        "required": False,
                        "help": "Maximum randomized jitter delay in seconds",
                    },
                    {
                        "name": "clear",
                        "type": "boolean",
                        "required": False,
                        "help": "Clear queue items",
                    },
                    {
                        "name": "dry-run",
                        "type": "boolean",
                        "required": False,
                        "help": "Simulate sends without dispatching",
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
    walls = config.get("walls", {})
    work_emails = ", ".join(walls.get("work", {}).get("emails", [])) or "(none configured)"
    personal_emails = ", ".join(walls.get("personal", {}).get("emails", [])) or "(none configured)"
    lines = [
        "imail — Apple Mail.app CLI (CLI preferred over MCP)",
        f"Walls: {work_emails} (Work) | {personal_emails} (Personal)",
        "",
        "Quick start:",
        "  imail doctor | imail walls | imail list --limit 10",
        '  imail send --from you@example.com --to a@b.com --subject "role update" --body-file "/path/letter.md" -a "/path/jd.pdf"',
        "",
        "Agent Guardrails & Writing Rules:",
        "  1. Reply Wall Integrity: Use exact receiving address when replying. Never cross work/personal walls.",
        "  2. Full Thread Review: Read full thread history before replying to prevent duplicate info.",
        "  3. Attachment Inspection: Read/analyze attachment text/PDF before sending to verify role/topic alignment.",
        "  4. Lowercase Subjects: Default initiated subjects to lowercase (e.g. 'senior full stack role').",
        "  5. No Body Headers / Emojis: Never put '# Subject' in body. 0 emojis in outreach/replies.",
        "  6. Markdown HTML Default: HTML Gmail Sans Serif ON by default. Quotes 'file.pdf' over backticks. No random bolding.",
        "  7. Tone & Sign-offs: Short, brief, polite. Max 1-2 '!'. Use natural sign-offs (Thanks, Talk soon, Cheers, Sincerely, Looking forward to our call).",
        "  8. Attachments: Prefer .pdf over .md files for attachments.",
        "  9. Draft Review: Use -o / --open to launch WebKit draft in Mail.app for review.",
        "",
        "Introspection: imail agent schema | imail agent guide",
        "",
        "Rules:",
    ]
    for rule in rules:
        lines.append(f"  • {rule}")
    return "\n".join(lines)
