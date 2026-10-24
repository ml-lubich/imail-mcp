# imail — Apple Mail CLI (+ agent schema)

`imail` is an agent-friendly command line for **Apple Mail.app** — list your
inbox, send mail, and auto-organize messages into folders, all without IMAP,
himalaya, or any mail server config. It drives Mail.app directly through
macOS Automation (AppleScript/`osascript`), so it needs nothing but Mail.app
itself and the accounts already configured in it.

```bash
imail doctor
imail list --limit 20
imail organize --account work --limit 100
```

For agent-friendly discovery, `imail -h` lists commands, `imail help` prints
examples, and `imail <command> -h` shows command options. Root options are
`-V/--version`, `-j/--json`, and `-q/--quiet`; shell completion is intentionally
not exposed as framework-generated root flags.

> **macOS only.** `imail` automates Mail.app via AppleScript, which only
> exists on macOS, and requires the OS-level Automation permission grant
> described below. There is no Linux/Windows build and none is planned —
> the tool has nothing to talk to on those platforms.

---

## Install

```bash
# Homebrew
brew install ml-lubich/tap/imail

# pipx (or uv, or pip)
pipx install imail-mcp          # or: uv tool install imail-mcp
                                 # or: pip install imail-mcp

imail -h
```

> The PyPI package is named `imail-mcp` (an older release also exists as
> `mac-imail`); the installed command is always `imail`.

<details>
<summary>Developing on <code>imail</code> itself</summary>

```bash
git clone https://github.com/ml-lubich/imail-mcp
cd imail-mcp
uv tool install .          # or: pip install -e ".[dev]"
imail -h
```

Run the test suite with `pytest -q` (requires the `dev` extra:
`pip install -e ".[dev]"`).

</details>

---

## Setup: grant Mail Automation permission

The first time `imail` talks to Mail.app, macOS will prompt you to allow your
terminal to control it. If it doesn't prompt, or you denied it by mistake,
grant it manually:

**System Settings → Privacy & Security → Automation** → find your terminal
app (Terminal, iTerm, etc.) → enable **Mail**.

Verify everything is wired up:

```bash
imail doctor
```

This confirms Mail.app is reachable and prints your configured accounts. If
it fails, re-check the Automation permission above and make sure Mail.app is
running with at least one account configured.

---

## Quick start

```bash
imail doctor                                     # check Mail.app is reachable
imail accounts                                    # list configured Mail.app accounts
imail list --limit 20                             # list INBOX messages
imail list --account Work --mailbox INBOX --json  # JSON output for scripts/agents
imail organize --account work --limit 100         # file INBOX into folders (move only)
imail send --from you@example.com --to a@b.com \
  --subject "Hi" --body "Hello"
imail version
```

`organize` **only moves** messages between mailboxes — it never deletes
anything. On each run it creates any of these folders that don't already
exist: `Action`, `Waiting`, `Meetings`, `IT`, `Releases`, `Security`, `FYI`,
`Personal`, `Archive` (plus `Job Applications` if you've created it
yourself), then files messages into them by subject-line pattern matching.

---

## Commands

| Command | What it does |
|---|---|
| `imail doctor` | Verify Mail.app is reachable via Automation |
| `imail accounts` | List Mail.app accounts (name + user) |
| `imail walls` | Print work/personal account walls from `accounts.json` |
| `imail list` | List inbox messages (`--account`, `--mailbox`, `--limit`, `--query`/`-q`, `--json`) |
| `imail search` | Search messages by query (subject or sender) (`<query>`, `-a`/`--account`, `-n`/`--limit`, `-j`/`--json`) |
| `imail read` | Read full message details, headers, attachments, and content (`<index>`, `-a`/`--account`, `-j`/`--json`) |
| `imail reply` | Reply to email by index with auto Reply-To and attachments (`<index>`, `-b`/`--body`, `-f`/`--body-file`, `-A`/`--attach`, `-F`/`--from`, `-t`/`--to`) |
| `imail organize` | Classify and move INBOX messages into folders (`--account`/`-a`, `--limit`/`-n`) — never deletes |
| `imail autodraft` | Scan personal inboxes; silent Mail.app drafts (or auto-send only low-stakes known follow-ups). `--dry-run`, `--account`, `--limit`. Scheduled by `brain reply`, not a second daemon. |
| `imail autodraft-eval` | Run the labeled eval (`src/imail/autodraft_eval.json`) against the real LLM; prints a scorecard, exits non-zero on any unsafe send |
| `imail autodraft-log` | Pretty-print the last N autodraft decisions from the log (`-n`/`--limit`, default 20) |
| `imail outreach draft` | Draft a source-grounded outreach email from JSON config and supplied company/candidate evidence; never sends |
| `imail send` | Send a message via Mail.app (`--from`, `--to`, `--subject`, `--body`, `-a`/`--attach`, `--cc`, `--markdown`) |
| `imail draft` | Save a draft silently in Mail.app without opening GUI windows (`--to`, `--subject`, `--body`/`--body-file`, `--from`, `-a`/`--attach`) |
| `imail status` | Show status of queued and sent batch emails |
| `imail batch` | Queue, manage, and dispatch batch emails with randomized intervals (`--file`, `--run`, `--limit`, `--clear`, `--dry-run`) |
| `imail version` | Print the installed version |
| `imail prompt` | Inspect or export system prompts and schemas (`--list`, `<name>`, `--json`) |
| `imail mcp` | Run the built-in MCP server over stdio (`doctor`, `list_accounts`, `list_messages`, `send_message`, `read_message`, `reply_message` tools) |
| `imail agent schema` | Print a JSON command catalog (name, help, params, account walls) for coding agents |
| `imail agent guide` | Print a plain-text usage guide for humans and agents |

Help is available everywhere: `imail -h`, `imail <command> -h`.

---

## Autodraft

`imail autodraft` scans your personal inboxes for messages that need a
reply, grounds a reply decision in the email body plus your `brain`
knowledge store via an LLM, and creates a silent, unsent Mail.app draft —
or, only in narrow cases, sends the reply outright.

**Guardrails:**

- A regex prefilter (`matches_skip_patterns`) drops obvious spam/newsletter/
  mass-blast senders before the LLM is ever called.
- The LLM's JSON decision is validated with exact types — any malformed
  field (wrong type, out-of-range confidence, unknown stakes value) is
  treated as an error, not silently coerced. This is fail-closed by design.
- The email body is untrusted input: the LLM prompt explicitly frames it as
  data to react to, never instructions to follow, since a message can try
  to talk the model into a fake high-confidence/low-stakes claim.
- Auto-send only fires when **all** of these hold (`auto_send_allowed`):
  confidence ≥ 0.95, stakes is `"low"`, the recipient is a known Contacts
  correspondent, the reply is ≤ 400 characters, the incoming message has no
  attachments, and the intent isn't `recruiter`.
- Recruiter emails are **never** auto-sent — always drafted, regardless of
  confidence.
- Every draft is created silently (no Mail.app GUI popup) and stays an
  **unsent draft** until you review and send it yourself.

**Commands:**

- `imail autodraft [--dry-run] [--account] [--limit]` — run the pipeline.
- `imail autodraft-eval` — run ~14 hand-labeled synthetic cases through the
  real LLM + gate and print a PASS/FAIL scorecard; exits non-zero if any
  case would have produced an unsafe auto-send.
- `imail autodraft-log [-n 20]` — pretty-print the last N logged decisions
  (`~/.config/imail/autodraft-log.jsonl`).

The OpenAI key (used for the primary `gpt-5-nano` backend, falling back to
`claude` haiku) is read from the environment (`OPENAI_API_KEY`) or, if
unset, the macOS keychain item named `OPENAI_API_KEY`.

Autodraft is entirely config-driven — no accounts, names, or resume paths
are hardcoded. It reads an optional `autodraft` block from your
`accounts.json` (see below):

```json
{
  "autodraft": {
    "accounts": ["you@gmail.com"],
    "owner_name": "jamie",
    "sign_as": "jamie",
    "resume_dir": "~/dev/resumes/resumes",
    "resume_default_variant": "base",
    "resume_variants": {
      "ai": ["ai", "ml", "llm", "agent"],
      "fullstack_ai": ["fullstack", "full stack"]
    }
  }
}
```

- `autodraft.accounts` — which addresses autodraft scans. Preferred over
  `walls.personal.emails` when you want autodraft scoped narrower than your
  general personal wall (e.g. to exclude an address you never want
  auto-drafted). If neither is set, `imail autodraft` raises a clear error.
- `owner_name` / `sign_as` — who the LLM triages on behalf of and what name
  it signs replies with. Both default to a neutral "the account owner" /
  no name if unset.
- `resume_dir` / `resume_default_variant` / `resume_variants` — only used
  for recruiter-intent replies. With no `resume_dir` set, autodraft never
  attaches a resume. `resume_variants` maps a folder name (under
  `resume_dir`) to the keywords that select it from the job text;
  `resume_default_variant` is the fallback folder when no keyword matches.

---

## Grounded outreach drafts

The `imail.outreach.draft_outreach` API prepares a company-specific referral
draft from role evidence and candidate facts supplied by the caller. The
structured LLM selects IDs from those inputs; `imail` builds the final factual
sentences from the selected records. It does not browse, send, or save a
message. The caller supplies source URLs and observation dates so stale or
unsupported company details can be screened before drafting.

```python
from imail.outreach import draft_outreach

draft = draft_outreach(
    company="Acme",
    contact_name="Taylor",
    role="Applied AI Engineer",
    role_description="Build agent workflows and evaluate their reliability.",
    candidate_name="Jordan",
    candidate_facts=[{"id": "f1", "text": "Jordan has shipped production AI agents."}],
    company_evidence=[{
        "id": "e1",
        "text": "AI agents for customer operations",
        "source_url": "https://example.com/careers",
        "observed_at": "2026-10-23",
    }],
    config={"enabled": True, "max_company_points": 1, "sign_as": "Referral Sender"},
    candidate_email="jordan@example.com",
)
```

`config.enabled` is an explicit opt-in; missing or false means no model call.
`max_company_points` is capped at three, and `max_candidate_points` controls
how many profile facts are selected. Both default to at most three. Company
evidence must include `source_url` and `observed_at` unless
`require_company_sources` is explicitly false. A custom `body_template` may
use only the supplied fields: `company`, `contact_name`, `role`,
`candidate_name`, `company_points`, `candidate_points`, `ask`, `sign_as`,
`candidate_contact`, and `website`. Model output is validated against known
IDs and configured limits; it cannot supply factual body text. The result
includes the draft body, selected points, and evidence references for review.

Evidence dates default to strict `YYYY-MM-DD` ISO format and a maximum age of
90 days. Set `max_evidence_age_days` to a non-negative integer to change the
freshness window. Future dates and unparseable dates fail closed. If a source
uses another date format, list its exact `strptime` pattern in
`accepted_date_formats`; no alternate format is inferred. Selected evidence
and candidate facts are normalized to plain text; markup, control characters,
and instruction-like content are rejected before they enter the draft.

The CLI exposes the same function without requiring a script:

```bash
imail outreach draft --config outreach-config.json --input outreach-evidence.json
```

The config JSON contains the personalization settings (including `enabled`,
point limits, ask, signoff, and optional body template). The input JSON contains
`company`, `contact_name`, `role`, `role_description`, `candidate_name`,
`candidate_facts`, `company_evidence`, and optional candidate contact fields.
The command prints a structured JSON result with the draft and evidence IDs; it
does not browse, send, or save mail. Use official company and current role
sources as evidence, and keep the source URL and observation date with each
company fact. Any downstream send still uses the regular `imail send` or
guarded `imail reply` flow and its account, recipient, and delivery checks.

The same structured ID-selection pattern can support other constrained tasks
such as niche dropdown choices: provide the allowed options and grounded
records as data, validate returned IDs against that list, and keep the action
that uses the selection in a separate reviewed step.

---

## Reliable sends and guarded replies

`imail read` includes the message's To and CC recipients. `imail list
--mailbox Outbox` and `imail read INDEX --mailbox Outbox` read Mail.app's
global Outbox; when an account is supplied, the read verifies the actual
sender account before returning a message.

`imail reply` pins the reviewed message by RFC Message-ID, re-reads that exact
message, and requires `--expected-recipient` to match its Reply-To address
before sending. `--expected-sender` and `--expected-message-id` provide extra
guards when the caller has recorded them. The MCP reply tool exposes the same
guards and CC support. Re-list and re-read a thread immediately before a reply;
do not reuse a mailbox index from an earlier scan.

After a network error, `imail send` and `imail reply` reconcile the exact
sender, recipient, CC, subject, body, and attachment set against Sent and the
global Outbox. They retry at most once by default, only for a recognized
connectivity failure and only after three checks confirm the exact message is
absent. A match in Sent is returned as provider-verified with its Message-ID.
A queued, ambiguous, or inaccessible result is `delivery_unknown`; the command
does not retry that message. Check Sent and Outbox before any manual retry.
Outbox count changes alone are never treated as delivery proof.

---

## Account walls (`accounts.json`)

If you juggle multiple Mail.app accounts (e.g. a work account and personal
accounts) and want `imail` to help keep them separate, create an
`accounts.json`. `imail` looks for it, in order, in the current directory,
the repo root (source checkouts), and `~/.config/imail/accounts.json` (the
stable location for an installed package):

```json
{
  "walls": {
    "work": { "accounts": ["Work"], "emails": ["you@work.example.com"] },
    "personal": { "accounts": ["Google"], "emails": ["you@gmail.com"] }
  },
  "aliases": { "work": "Work", "google": "Google" },
  "rules": ["Auto-send MUST set --from matching the correct wall."]
}
```

- `walls` / `rules` are surfaced by `imail walls`, `imail agent schema`, and
  `imail agent guide` — informational, not enforced by `send` itself.
- `aliases` lets `imail organize --account <alias>` accept short names
  instead of the exact Mail.app account name.
- `accounts.json` is only required for `walls`, `agent schema`, `agent
  guide`, `autodraft`, and `organize --account <alias>`; `doctor`,
  `accounts`, `list`, `send`, and a plain `imail organize` (all accounts)
  work without it.

---

## Using `imail` from a coding agent

`imail agent schema` prints a JSON catalog of every command, its parameters,
and your configured account walls — enough for an agent to construct valid
`imail` invocations without parsing `--help` output:

```bash
imail agent schema   # machine-readable command catalog
imail agent guide     # short usage guide (CLI-first, wall rules) for humans/agents
```

`imail` is a CLI meant to be called directly from agent shells, which is
cheaper on tokens than a tool-calling round trip — prefer that where the
agent's harness allows arbitrary shell commands.

For harnesses that only speak MCP (Model Context Protocol), `imail` also
ships a built-in stdio MCP server exposing four tools (`doctor`,
`list_accounts`, `list_messages`, `send_message`):

```bash
imail mcp   # runs an MCP server over stdio; exits on EOF/SIGTERM
```

Point an MCP client at it, e.g. in a Claude Desktop / Claude Code
`mcp_servers` (or `.mcp.json`) config:

```json
{
  "mcpServers": {
    "imail": {
      "command": "imail",
      "args": ["mcp"]
    }
  }
}
```

If you need a broader MCP server for Mail.app (more tools than the four
above), [patrickfreyer/apple-mail-mcp](https://github.com/patrickfreyer/apple-mail-mcp)
is a community option.

---

MIT License · Copyright (c) 2026 Misha Lubich ([ml-lubich](https://github.com/ml-lubich))
