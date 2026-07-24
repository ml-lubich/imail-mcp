"""Apple Mail.app integration via osascript."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def accounts_json_path() -> Path:
    """Locate accounts.json at repo root (dev) or cwd."""
    pkg_dir = Path(__file__).resolve().parent
    candidates = [
        pkg_dir.parent.parent / "accounts.json",
        Path.cwd() / "accounts.json",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "accounts.json not found — expected at repo root or current directory"
    )


def load_accounts_config() -> dict[str, Any]:
    return json.loads(accounts_json_path().read_text(encoding="utf-8"))


def run_as(script: str) -> str:
    result = subprocess.run(
        ["osascript"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "osascript failed").strip())
    return (result.stdout or "").strip()


def escape_applescript(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def doctor() -> str:
    run_as('tell application "Mail" to get name')
    return "ok: Mail.app reachable"


def list_accounts() -> list[tuple[str, str]]:
    out = run_as(
        """
tell application "Mail"
  set out to ""
  repeat with a in accounts
    set out to out & (name of a) & tab & (user name of a) & linefeed
  end repeat
  return out
end tell
"""
    )
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        if "\t" in line:
            name, user = line.split("\t", 1)
            rows.append((name.strip(), user.strip()))
    return rows


def format_accounts() -> str:
    return "\n".join(f"{name}\t{user}" for name, user in list_accounts())


def format_walls() -> str:
    config = load_accounts_config()
    walls = config.get("walls", {})
    work = walls.get("work", {})
    personal = walls.get("personal", {})
    lines = [
        "WORK: " + ", ".join(work.get("accounts", [])),
        "  emails: " + ", ".join(work.get("emails", [])),
        "PERSONAL: " + ", ".join(personal.get("accounts", [])),
        "  emails: " + ", ".join(personal.get("emails", [])),
        "primary Google: " + personal.get("primary_google", ""),
        "---",
    ]
    for rule in config.get("rules", []):
        lines.append(f"• {rule}")
    return "\n".join(lines)


def list_messages(
    account: str = "",
    mailbox: str = "INBOX",
    limit: int = 20,
) -> list[dict[str, str]]:
    script = f"""
on run argv
  set acctName to item 1 of argv
  set boxName to item 2 of argv
  set lim to (item 3 of argv) as integer
  set out to ""
  tell application "Mail"
    if acctName is "" then
      set box to inbox
    else
      set acct to missing value
      repeat with a in accounts
        if (name of a is acctName) or (user name of a is acctName) then
          set acct to a
          exit repeat
        end if
      end repeat
      if acct is missing value then error "account not found: " & acctName
      if boxName is "INBOX" or boxName is "Inbox" then
        try
          set box to mailbox "INBOX" of acct
        on error
          try
            set box to mailbox "Inbox" of acct
          on error
            set box to inbox
          end try
        end try
      else
        set box to mailbox boxName of acct
      end if
    end if
    set msgs to messages of box
    set n to count of msgs
    if n > lim then set n to lim
    repeat with i from 1 to n
      set m to item i of msgs
      set subj to subject of m
      set snd to sender of m
      set dt to date received of m
      set out to out & i & tab & (dt as string) & tab & snd & tab & subj & linefeed
    end repeat
  end tell
  return out
end run
"""
    result = subprocess.run(
        ["osascript", "-", account, mailbox, str(limit)],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "osascript failed").strip())
    out = (result.stdout or "").strip()
    rows: list[dict[str, str]] = []
    for line in out.splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 4:
            idx, date, sender, subject = parts
            rows.append(
                {
                    "index": idx,
                    "date": date,
                    "sender": sender,
                    "subject": subject,
                }
            )
    return rows


def format_list_messages(
    account: str = "",
    mailbox: str = "INBOX",
    limit: int = 20,
) -> str:
    return "\n".join(
        f"{row['index']}\t{row['date']}\t{row['sender']}\t{row['subject']}"
        for row in list_messages(account=account, mailbox=mailbox, limit=limit)
    )


def send_message(
    to: str,
    subject: str,
    body: str,
    from_addr: str,
    cc: str = "",
) -> str:
    to_e = escape_applescript(to)
    subject_e = escape_applescript(subject)
    body_e = escape_applescript(body)
    from_e = escape_applescript(from_addr)
    cc_e = escape_applescript(cc)
    cc_block = ""
    if cc_e:
        cc_block = f"""
  tell msg
    make new cc recipient at end of cc recipients with properties {{address:"{cc_e}"}}
  end tell
"""
    script = f"""
tell application "Mail"
  set msg to make new outgoing message with properties {{subject:"{subject_e}", content:"{body_e}", visible:false}}
  tell msg
    make new to recipient at end of to recipients with properties {{address:"{to_e}"}}
  end tell
{cc_block}
  if "{from_e}" is not "" then
    repeat with a in accounts
      if (user name of a) is "{from_e}" then
        set sender of msg to "{from_e}"
        exit repeat
      end if
    end repeat
  end if
  send msg
end tell
return "OK sent to {to_e}"
"""
    return run_as(script)
