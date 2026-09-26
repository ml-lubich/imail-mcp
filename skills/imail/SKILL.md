---
name: imail
description: Send, list, organize, and auto-draft Apple Mail.app email via the `imail` CLI (a.k.a. imail-mcp) — no IMAP, no mail server config, driven entirely by AppleScript. Use whenever a task means sending an email, drafting one, listing/triaging an inbox, auto-organizing an inbox into folders, or resolving whether an address is a known Contacts.app correspondent. Also use when a harness only speaks MCP and needs a stdio MCP server for Mail.app (`doctor`, `list_accounts`, `list_messages`, `send_message` tools). Triggers include "email X", "send a mail", "check my inbox", "organize my mail", "draft a reply", "is this address in my contacts".
---

# imail

Agent-friendly Apple Mail.app CLI. Everything goes through AppleScript/`osascript`
against the already-configured Mail.app accounts on this Mac — there is no IMAP
client, no SMTP config, and no stored credentials.

## Install

From a local checkout:

```bash
uv tool install -e ~/dev/imail-mcp
```

From git (what a fresh clone does):

```bash
git clone https://github.com/ml-lubich/imail-mcp && uv tool install -e ./imail-mcp
```

This installs the `imail` command (`imail.cli:app`, Typer-based, Python >=3.10).

## Key CLI commands (real flags, from `--help`)

| Command | Purpose | Key flags |
|---|---|---|
| `imail doctor` | Verify Mail.app is reachable | — |
| `imail accounts` | List Mail.app accounts | — |
| `imail walls` | Print work vs personal walls from `accounts.json` | — |
| `imail list` | List inbox messages | `--account`, `--mailbox` (default `INBOX`), `--limit` (default 20), `--json` |
| `imail organize` | Move-only inbox triage into folders — never deletes | `-a/--account`, `-n/--limit` (default 200) |
| `imail send` | Send a message via Mail.app | `--from` (required), `--to` (required), `--subject` (required), `--body`, `--body-file`, `--cc`, `-a/--attach` (repeatable), `-m/--markdown` (on by default), `--zip-attachments`, `-o/--open`, `-H/--humanize` |
| `imail draft` | Save a draft silently, no GUI window | `-t/--to`, `-s/--subject`, `-b/--body`, `-f/--body-file`, `-F/--from`, `-c/--cc`, `-a/--attach`, `-H/--humanize` |
| `imail batch` | Queue/dispatch batch emails with randomized jitter | `-f/--file`, `-r/--run`, `-n/--limit` (0=all), `--min-delay`/`--max-delay`, `--clear`, `--dry-run`, `--queue-file` |
| `imail status` | Show queued/sent batch email status | `--queue-file` |
| `imail autodraft` | Scan personal inbox, create silent drafts, auto-send only high-confidence | see `autodraft` config in `accounts.json` |
| `imail autodraft-eval` | Run the labeled eval against the real LLM, scorecard | — |
| `imail autodraft-log` | Pretty-print last N autodraft decisions | `-n/--limit` (default 20) |
| `imail version` | Print installed version | — |
| `imail agent schema` / `imail agent guide` | Machine-readable / human-readable command catalog | — |
| `imail mcp` | Run the built-in MCP server over stdio | — |

Run `imail <command> --help` for the authoritative flag list; the table above
is a summary, not a substitute.

## MCP server

`imail` ships a built-in stdio MCP server exposing four tools: `doctor`,
`list_accounts`, `list_messages`, `send_message`.

Launch it directly:

```bash
imail mcp
```

Register it with Claude Code:

```bash
claude mcp add imail -- imail mcp
```

Or in a raw `mcpServers` / `.mcp.json` block:

```json
{
  "mcpServers": {
    "imail": { "command": "imail", "args": ["mcp"] }
  }
}
```

## Required macOS permissions

All mail/contacts access goes through `osascript` automation, so macOS will
prompt for **Automation** access (System Settings → Privacy & Security →
Automation) the first time each of these is used, for whichever terminal/app
runs `imail`:

- **Mail.app** — every command (`list`, `send`, `organize`, `autodraft`, etc.)
- **System Events** — used to keep Mail.app hidden in the background while
  sending/drafting (`hide_prefix`/`hide_suffix` in `src/imail/mail.py`)
- **Contacts.app** — only for `is_known_correspondent` lookups (used by
  `autodraft` to decide reply confidence)

No Full Disk Access, Calendars, or Photos access is needed.

Trigger the Automation permission popup with a harmless read (does not send
or mutate anything):

```bash
imail doctor
```

## Safety rules

- **Read-only by default.** `list`, `doctor`, `accounts`, `walls`, `status`,
  and `autodraft-log` never send, move, or delete anything.
- `organize` **moves** messages between mailboxes — it never deletes.
- `send`, `draft`, `batch --run`, and `autodraft` (in auto-send mode) are the
  only commands that put mail on the wire or create drafts. Only run these
  when the user has explicitly asked for a message to go out; never invoke
  them speculatively in a test or check.
- `send --from` is required and must match a configured wall in
  `accounts.json` — never guess or hardcode a sender address.
