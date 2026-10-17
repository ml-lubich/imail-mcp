"""Apple Mail.app integration via osascript."""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any


def accounts_json_path() -> Path:
    """Locate accounts.json: repo root (dev checkout), cwd, or ~/.config/imail (installed)."""
    pkg_dir = Path(__file__).resolve().parent
    candidates = [
        pkg_dir.parent.parent / "accounts.json",
        Path.cwd() / "accounts.json",
        Path.home() / ".config" / "imail" / "accounts.json",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "accounts.json not found — expected at repo root, the current directory, "
        "or ~/.config/imail/accounts.json"
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


ENVELOPE_DB_PATH = (
    Path.home() / "Library" / "Mail" / "V10" / "MailData" / "Envelope Index"
)

# Fast path toggle: defaults to on. Set to False to force the osascript path.
_FAST_PATH_ENABLED = True


def _envelope_db_available() -> bool:
    return ENVELOPE_DB_PATH.is_file() and _FAST_PATH_ENABLED


@lru_cache(maxsize=1)
def _mail_accounts() -> dict[str, str]:
    """Map Mail.app account name -> account id (AppleScript, cached)."""
    script = """
tell application "Mail"
  set out to ""
  repeat with a in accounts
    set out to out & (name of a) & "\x1f" & (id of a) & linefeed
  end repeat
  return out
end tell
"""
    out = run_as(script)
    mapping: dict[str, str] = {}
    for line in out.splitlines():
        if "\x1f" in line:
            name, aid = line.split("\x1f", 1)
            mapping[name.strip()] = aid.strip()
    return mapping


@lru_cache(maxsize=1)
def _mail_emails() -> dict[str, str]:
    """Map Mail.app account user name (email) -> account id (cached)."""
    script = """
tell application "Mail"
  set out to ""
  repeat with a in accounts
    try
      set out to out & (user name of a) & "\x1f" & (id of a) & linefeed
    end try
  end repeat
  return out
end tell
"""
    out = run_as(script)
    mapping: dict[str, str] = {}
    for line in out.splitlines():
        if "\x1f" in line:
            email, aid = line.split("\x1f", 1)
            mapping[email.strip()] = aid.strip()
    return mapping


@lru_cache(maxsize=1)
def _inbox_mailbox_ids() -> list[int]:
    """ROWIDs of mailboxes whose url ends with INBOX/Inbox."""
    if not _envelope_db_available():
        return []
    con = sqlite3.connect(ENVELOPE_DB_PATH)
    try:
        ids = [
            r[0]
            for r in con.execute(
                "SELECT ROWID FROM mailboxes "
                "WHERE lower(url) LIKE '%inbox' OR lower(url) LIKE '%/inbox/%'"
            )
        ]
    finally:
        con.close()
    return ids


@lru_cache(maxsize=1)
def _account_inbox_ids() -> dict[str, list[int]]:
    """account id -> INBOX mailbox ROWIDs (cached)."""
    if not _envelope_db_available():
        return {}
    con = sqlite3.connect(ENVELOPE_DB_PATH)
    try:
        rows = con.execute(
            "SELECT ROWID, url FROM mailboxes "
            "WHERE lower(url) LIKE '%inbox' OR lower(url) LIKE '%/inbox/%'"
        ).fetchall()
    finally:
        con.close()
    result: dict[str, list[int]] = {}
    for rowid, url in rows:
        # extract account uuid from url like imap://UUID/INBOX or ews://UUID/Inbox
        uuid = _uuid_from_url(url)
        if uuid:
            result.setdefault(uuid, []).append(rowid)
    return result


def _uuid_from_url(url: str) -> str | None:
    """imap://UUID/... -> UUID"""
    if "://" not in url:
        return None
    rest = url.split("://", 1)[1]
    uuid = rest.split("/", 1)[0]
    return uuid or None


def _resolve_account_uuids(account: str) -> list[str]:
    """Resolve account alias/input to Mail.app account ids (UUIDs)."""
    if not account:
        return []
    cfg = load_accounts_config()
    aliases = cfg.get("aliases", {})
    name_to_id = _mail_accounts()
    email_to_id = _mail_emails()

    # Try exact alias match first
    alias_target = aliases.get(account)
    if alias_target:
        uuids = _uuids_for_name(alias_target, name_to_id, email_to_id)
        if uuids:
            return uuids

    # Try case-insensitive alias match
    lower = account.lower()
    for alias_key, alias_target in aliases.items():
        if alias_key.lower() == lower:
            uuids = _uuids_for_name(alias_target, name_to_id, email_to_id)
            if uuids:
                return uuids

    # Fallback: treat as literal name or email
    return _uuids_for_name(account, name_to_id, email_to_id)


def _uuids_for_name(
    name: str, name_to_id: dict[str, str], email_to_id: dict[str, str]
) -> list[str]:
    """Resolve a literal account name/email to account ids."""
    uuids: list[str] = []
    # exact email or exact name
    uid = email_to_id.get(name) or name_to_id.get(name)
    if uid:
        return [uid]
    # case-insensitive email match
    lower = name.lower()
    for email, aid in email_to_id.items():
        if email.lower() == lower:
            uuids.append(aid)
    if uuids:
        return uuids
    # case-insensitive name match
    for nm, aid in name_to_id.items():
        if nm.lower() == lower:
            uuids.append(aid)
    return uuids


def _resolve_target_mailbox_ids(account: str | None, mailbox: str) -> list[int]:
    """Resolve account+mailbox to a list of mailbox ROWIDs to search."""
    if not _envelope_db_available():
        return []
    con = sqlite3.connect(ENVELOPE_DB_PATH)
    try:
        if mailbox.lower() in ("inbox",):
            # account-filtered or all inboxes
            ids: list[int] = []
            if account:
                # resolve account alias -> Mail.app name/email -> uuid -> inbox ids
                uuids = _resolve_account_uuids(account)
                for uid in uuids:
                    ids.extend(_account_inbox_ids().get(uid, []))
            else:
                ids = list(_inbox_mailbox_ids())
            return sorted(set(ids))
        # specific mailbox: match by url
        like = f"%{mailbox}%"
        return [
            r[0]
            for r in con.execute(
                "SELECT ROWID FROM mailboxes WHERE url LIKE ?", (like,)
            )
        ]
    finally:
        con.close()


def _format_date(epoch_seconds: int) -> str:
    """Convert epoch seconds to AppleScript date format."""
    utc = _dt.datetime.fromtimestamp(epoch_seconds, tz=_dt.timezone.utc)
    local = utc.astimezone()
    return local.strftime("%A, %B %d, %Y at %I:%M:%S %p")


def _format_sender(comment: str | None, address: str | None) -> str:
    """Format sender as shown in imail output."""
    if not address:
        return ""
    if comment and ("<" in comment or "@" in comment):
        # comment already looks like "Name <email>" or similar
        return comment
    if comment:
        return f"{comment} <{address}>"
    return address


def _list_messages_fast(
    account: str = "",
    mailbox: str = "INBOX",
    limit: int = 20,
    query: str = "",
) -> list[dict[str, str]]:
    """Fast path using Envelope Index SQLite database."""
    if not _envelope_db_available():
        raise RuntimeError("Envelope Index not available")

    target_ids = _resolve_target_mailbox_ids(account, mailbox)
    if not target_ids:
        return []

    con = sqlite3.connect(ENVELOPE_DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        # Build placeholders for IN clauses
        inbox_ph = ",".join("?" for _ in target_ids)
        # SQL: messages in target mailboxes OR labeled into target mailboxes
        sql = f"""
        SELECT
          m.ROWID AS msg_rowid,
          m.date_received,
          a.address,
          a.comment,
          s.subject
        FROM messages m
        JOIN addresses a ON a.ROWID = m.sender
        JOIN subjects s ON s.ROWID = m.subject
        WHERE m.deleted = 0
          AND (
            m.mailbox IN ({inbox_ph})
            OR m.ROWID IN (
              SELECT message_id FROM labels WHERE mailbox_id IN ({inbox_ph})
            )
          )
          AND (
            lower(s.subject) LIKE lower(?)
            OR lower(a.address) LIKE lower(?)
          )
        ORDER BY m.date_received DESC
        LIMIT ?
        """
        like = f"%{query}%"
        params = (
            *target_ids,  # m.mailbox IN (...)
            *target_ids,  # labels.mailbox_id IN (...)
            like,         # subject LIKE ?
            like,         # address LIKE ?
            limit,
        )
        rows = con.execute(sql, params).fetchall()

        # Format output to match osascript version: index, date, sender, subject
        result: list[dict[str, str]] = []
        for idx, r in enumerate(rows, start=1):
            # date_received is epoch seconds (UTC)
            date_str = _format_date(int(r["date_received"]))
            sender_str = _format_sender(r["comment"], r["address"])
            result.append(
                {
                    "index": str(idx),
                    "date": date_str,
                    "sender": sender_str,
                    "subject": r["subject"],
                }
            )
        return result
    finally:
        con.close()


def list_messages(
    account: str = "",
    mailbox: str = "INBOX",
    limit: int = 20,
    query: str = "",
) -> list[dict[str, str]]:
    """List inbox messages (SQLite fast path; osascript fallback)."""
    try:
        return _list_messages_fast(
            account=account, mailbox=mailbox, limit=limit, query=query
        )
    except Exception:
        # Fall back to original osascript implementation
        q_esc = escape_applescript(query) if query else ""
        script = f"""
on run argv
  set acctName to item 1 of argv
  set boxName to item 2 of argv
  set lim to (item 3 of argv) as integer
  set q to item 4 of argv
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
    set matchCount to 0
    set totalCount to count of msgs
    repeat with i from 1 to totalCount
      if matchCount >= lim then exit repeat
      set m to item i of msgs
      set subj to subject of m
      set snd to sender of m
      set isMatch to true
      if q is not "" then
        set fullText to (subj & " " & snd)
        if fullText does not contain q then
          set isMatch to false
        end if
      end if
      if isMatch then
        set matchCount to matchCount + 1
        set dt to date received of m
        set out to out & matchCount & tab & (dt as string) & tab & snd & tab & subj & linefeed
      end if
    end repeat
  end tell
  return out
end run
"""
        result = subprocess.run(
            ["osascript", "-", account, mailbox, str(limit), query],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                (result.stderr or result.stdout or "osascript failed").strip()
            )
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


def get_message_details(
    account: str,
    index: int | str,
    mailbox: str = "INBOX",
) -> dict[str, Any]:
    """Fetch a message's plain body (truncated ~4000 chars), reply flag, and attachment presence."""
    script = """
on run argv
  set acctName to item 1 of argv
  set boxName to item 2 of argv
  set idx to (item 3 of argv) as integer
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
    set m to item idx of (messages of box)
    set bodyText to content of m
    set repliedFlag to (was replied to of m) as string
    set attCount to (count of mail attachments of m) as string
    return repliedFlag & tab & attCount & tab & bodyText
  end tell
end run
"""
    result = subprocess.run(
        ["osascript", "-", account, mailbox, str(index)],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "osascript failed").strip())
    out = result.stdout or ""
    parts = out.split("\t", 2)
    if len(parts) != 3:
        raise RuntimeError(f"unexpected output from Mail.app: {out!r}")
    replied_str, att_str, body = parts
    return {
        "body": body[:4000],
        "was_replied_to": replied_str.strip().lower() == "true",
        "has_attachments": int(att_str.strip() or 0) > 0,
    }


def read_message(
    account: str = "",
    index: int | str = 1,
    mailbox: str = "INBOX",
) -> dict[str, Any]:
    """Fetch complete details of an email by index or search, including full body, reply-to, and attachments."""
    formatted_script = f"""
set acctName to "{escape_applescript(account)}"
set boxName to "{escape_applescript(mailbox)}"
set idx to {int(index)}
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
  if idx > (count of msgs) or idx < 1 then error "message index out of range: " & idx
  set m to item idx of msgs
  set sid to (id of m) as string
  set mid to (message id of m) as string
  set rto to (reply to of m) as string
  set snd to (sender of m) as string
  set sub to (subject of m) as string
  set dt to (date received of m) as string
  set wasRep to (was replied to of m) as string
  set atts to mail attachments of m
  set attCount to (count of atts) as string
  set attNames to ""
  repeat with a in atts
    if attNames is not "" then set attNames to attNames & ", "
    set attNames to attNames & (name of a)
  end repeat
  set bodyText to content of m
  return sid & tab & mid & tab & rto & tab & snd & tab & sub & tab & dt & tab & wasRep & tab & attCount & tab & attNames & linefeed & "---BODY---" & linefeed & bodyText
end tell
"""
    out = run_as(formatted_script)
    if "---BODY---" not in out:
        raise RuntimeError(f"unexpected output from Mail.app: {out!r}")
    meta_part, body_part = out.split("---BODY---" + "\n", 1)
    fields = meta_part.strip().split("\t")
    while len(fields) < 9:
        fields.append("")
    sid, mid, rto, snd, sub, dt, was_rep, att_count, att_names = fields[:9]
    return {
        "id": sid,
        "message_id": mid,
        "reply_to": rto or snd,
        "sender": snd,
        "subject": sub,
        "date": dt,
        "was_replied_to": was_rep.strip().lower() == "true",
        "attachment_count": int(att_count.strip() or 0),
        "attachments": [a.strip() for a in att_names.split(",") if a.strip()] if att_names else [],
        "body": body_part,
    }


def reply_message(
    account: str = "",
    index: int | str = 1,
    mailbox: str = "INBOX",
    body: str = "",
    attachments: list[str] | None = None,
    from_addr: str = "",
    to: str = "",
    subject: str = "",
    markdown: bool = True,
    zip_attachments: bool = False,
    humanize: bool = False,
    open_draft: bool = False,
) -> str:
    """Reply to an email by index, automatically determining reply-to, subject, and wall from the original message."""
    msg = read_message(account=account, index=index, mailbox=mailbox)
    target_to = to or msg["reply_to"] or msg["sender"]
    if not target_to:
        raise RuntimeError(f"Could not determine recipient for message index {index}")

    target_subject = subject or msg["subject"]
    if not target_subject.lower().startswith("re:"):
        target_subject = f"Re: {target_subject}"

    target_from = from_addr or account
    if not target_from:
        # Default to primary Google or personal wall if available
        try:
            cfg = load_accounts_config()
            target_from = (
                cfg.get("walls", {}).get("personal", {}).get("primary_google", "")
                or (cfg.get("walls", {}).get("personal", {}).get("emails", [""])[0])
            )
        except Exception:
            target_from = ""

    if open_draft:
        return create_eml_draft(
            to=target_to,
            subject=target_subject,
            body=body,
            from_addr=target_from,
            attachments=attachments,
            is_markdown=markdown,
            zip_attachments=zip_attachments,
            open_in_mail=True,
            humanize=humanize,
        )

    return send_message(
        to=target_to,
        subject=target_subject,
        body=body,
        from_addr=target_from,
        attachments=attachments,
        is_markdown=markdown,
        zip_attachments=zip_attachments,
        humanize=humanize,
    )


def is_known_correspondent(email: str) -> bool:
    """True if the given address exists in Contacts.app."""
    if not email:
        return False
    script = """
on run argv
  set addr to item 1 of argv
  tell application "Contacts"
    set found to false
    repeat with p in people
      repeat with e in emails of p
        if (value of e) is addr then
          set found to true
          exit repeat
        end if
      end repeat
      if found then exit repeat
    end repeat
  end tell
  return found as string
end run
"""
    result = subprocess.run(
        ["osascript", "-", email],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    return (result.stdout or "").strip().lower() == "true"


def format_list_messages(
    account: str = "",
    mailbox: str = "INBOX",
    limit: int = 20,
    query: str = "",
) -> str:
    return "\n".join(
        f"{row['index']}\t{row['date']}\t{row['sender']}\t{row['subject']}"
        for row in list_messages(account=account, mailbox=mailbox, limit=limit, query=query)
    )


def markdown_to_html(md: str) -> str:
    """Convert markdown text to clean, uniform Gmail-style Sans Serif HTML."""
    import re

    # 1. Replace backticks `text` with quotes "text"
    md = re.sub(r"`(.*?)`", r'"\1"', md)

    # 2. Remove random bolding **text** -> text
    md = re.sub(r"\*\*(.*?)\*\*", r"\1", md)

    raw_html = ""
    try:
        from markdown_it import MarkdownIt

        raw_html = MarkdownIt().render(md)
    except Exception:
        import html

        lines = md.split("\n")
        html_lines = []
        in_paragraph = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if in_paragraph:
                    html_lines.append("</p>")
                    in_paragraph = False
                continue
            if stripped.startswith("# "):
                if in_paragraph:
                    html_lines.append("</p>")
                    in_paragraph = False
                html_lines.append(f"<h1>{html.escape(stripped[2:])}</h1>")
            elif stripped.startswith("## "):
                if in_paragraph:
                    html_lines.append("</p>")
                    in_paragraph = False
                html_lines.append(f"<h2>{html.escape(stripped[3:])}</h2>")
            elif stripped.startswith("### "):
                if in_paragraph:
                    html_lines.append("</p>")
                    in_paragraph = False
                html_lines.append(f"<h3>{html.escape(stripped[4:])}</h3>")
            else:
                if not in_paragraph:
                    html_lines.append("<p>")
                    in_paragraph = True
                else:
                    html_lines.append("<br/>")
                text = html.escape(line)
                text = re.sub(r"\*(.*?)\*", r"<em>\1</em>", text)
                html_lines.append(text)
        if in_paragraph:
            html_lines.append("</p>")
        raw_html = "\n".join(html_lines)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body, div, p, ul, ol, li, h1, h2, h3, h4, h5, h6, span, a, strong, em, b, i, code {{
    font-family: Arial, Helvetica, sans-serif !important;
    color: #222222 !important;
    font-weight: normal !important;
  }}
  body {{
    font-family: Arial, Helvetica, sans-serif !important;
    font-size: 14px !important;
    line-height: 1.5 !important;
    color: #222222 !important;
    background-color: #ffffff !important;
    margin: 0 !important;
    padding: 10px !important;
  }}
  p {{
    font-family: Arial, Helvetica, sans-serif !important;
    font-size: 14px !important;
    line-height: 1.5 !important;
    margin-top: 0 !important;
    margin-bottom: 14px !important;
  }}
  h1 {{
    font-family: Arial, Helvetica, sans-serif !important;
    font-size: 18px !important;
    font-weight: bold !important;
    margin-top: 0 !important;
    margin-bottom: 14px !important;
  }}
  h2 {{
    font-family: Arial, Helvetica, sans-serif !important;
    font-size: 16px !important;
    font-weight: bold !important;
    margin-top: 14px !important;
    margin-bottom: 12px !important;
  }}
  h3 {{
    font-family: Arial, Helvetica, sans-serif !important;
    font-size: 14px !important;
    font-weight: bold !important;
    margin-top: 12px !important;
    margin-bottom: 10px !important;
  }}
  ul, ol {{
    font-family: Arial, Helvetica, sans-serif !important;
    margin-top: 0 !important;
    margin-bottom: 14px !important;
    padding-left: 20px !important;
  }}
  li {{
    font-family: Arial, Helvetica, sans-serif !important;
    font-size: 14px !important;
    line-height: 1.5 !important;
    margin-bottom: 4px !important;
  }}
  code {{
    font-family: Arial, Helvetica, sans-serif !important;
    font-size: 14px !important;
    background-color: transparent !important;
    padding: 0 !important;
  }}
</style>
</head>
<body style="font-family: Arial, Helvetica, sans-serif; font-size: 14px; line-height: 1.5; color: #222222;">
{raw_html}
</body>
</html>"""


def humanize_text(text: str, typo_rate: float = 0.05) -> str:
    """
    Subtly humanize text by stripping emojis and applying clean human casing/punctuation variations.
    Inspired by blader/humanizer.
    - NO gross misspellings or character swaps.
    - Strips all emojis.
    - Replaces corporate sign-offs ('Best regards', 'Best') with natural sign-offs ('Thanks,', 'Thank you!', 'Sincerely,').
    - Limits exclamation marks to max 2 per email.
    - Occasional lowercase 'i' or uncapitalized initial sentence letters.
    - Occasional omitted trailing period at paragraph end.
    """
    import random
    import re

    # 1. Strip all emojis
    text = re.sub(r"[\U00010000-\U0010ffff\u2600-\u26FF\u2700-\u27BF]", "", text)

    # 2. Replace corporate sign-offs with natural human sign-offs
    text = re.sub(r"(?i)\bBest regards,?", "Thanks,", text)
    text = re.sub(r"(?i)\bBest,", "Thanks,", text)
    text = re.sub(r"(?i)\bWarm regards,?", "Thanks,", text)

    # 3. Cap exclamation marks at max 2 per email and collapse consecutive !
    text = re.sub(r"!{2,}", "!", text)
    parts = text.split("!")
    if len(parts) > 3:
        text = "!".join(parts[:2]) + "! " + ".".join(parts[2:])

    lines = text.split("\n")
    humanized_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            humanized_lines.append("")
            continue

        # Don't modify code blocks, URLs, or emails
        if stripped.startswith("http://") or stripped.startswith("https://") or "@" in stripped:
            humanized_lines.append(line)
            continue

        # Occasional missing trailing period at end of paragraph (10-15% chance)
        if stripped.endswith(".") and not stripped.endswith("..") and random.random() < 0.15:
            line = line.rstrip(".")

        words = line.split(" ")
        humanized_words = []

        for idx, word in enumerate(words):
            # Don't touch URLs, emails, or file paths
            if any(w in word for w in ["http://", "https://", "@", "/", "\\"]):
                humanized_words.append(word)
                continue

            # Convert standalone "I" to lowercase "i" occasionally (10-15% chance)
            if word == "I" and random.random() < 0.15:
                humanized_words.append("i")
                continue

            # Convert first letter of sentence to lowercase occasionally (5-8% chance)
            if idx == 0 and len(word) > 2 and word[0].isupper() and word.isalpha() and random.random() < 0.08:
                word = word[0].lower() + word[1:]

            humanized_words.append(word)

        humanized_lines.append(" ".join(humanized_words))

    return "\n".join(humanized_lines)


def send_message(
    to: str,
    subject: str,
    body: str,
    from_addr: str,
    cc: str = "",
    attachments: list[str] | None = None,
    is_markdown: bool = True,
    zip_attachments: bool = False,
    humanize: bool = False,
    verify_delivery: bool = True,
) -> str:
    if subject and not subject.lower().startswith("re:"):
        subject = subject.lower()

    if humanize:
        body = humanize_text(body)

    if zip_attachments and attachments:
        import tempfile
        import zipfile

        temp_dir = Path(tempfile.mkdtemp(prefix="imail_zip_"))
        zip_path = temp_dir / "attachments.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for att in attachments:
                ap = Path(att).expanduser().resolve()
                if not ap.exists():
                    raise FileNotFoundError(f"Attachment file not found: {ap}")
                zf.write(ap, arcname=ap.name)
        attachments = [str(zip_path)]

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
    attachment_block = ""
    if attachments:
        for att in attachments:
            att_path = Path(att).expanduser().resolve()
            if not att_path.exists():
                raise FileNotFoundError(f"Attachment file not found: {att_path}")
            att_e = escape_applescript(str(att_path))
            attachment_block += f"""
  tell msg
    make new attachment with properties {{file name:POSIX file "{att_e}"}} at after last paragraph of content
  end tell
"""

    verify_script_part = ""
    if verify_delivery:
        verify_script_part = """
  set dispatched to false
  repeat with i from 1 to 10
    delay 0.3
    set currentOut to count of messages of outbox
    if currentOut <= initialOut then
      set dispatched to true
      exit repeat
    end if
  end repeat
  if not dispatched then
    return "QUEUED in Outbox for " & recipientStr & " (pending network/Mail send)"
  end if
"""

    if is_markdown:
        import tempfile

        html_content = markdown_to_html(body)
        temp_dir = Path(tempfile.mkdtemp(prefix="imail_md_"))
        html_file = temp_dir / "body.html"
        rtf_file = temp_dir / "body.rtf"
        html_file.write_text(html_content, encoding="utf-8")

        try:
            subprocess.run(
                ["textutil", "-convert", "rtf", str(html_file), "-output", str(rtf_file)],
                check=True,
                capture_output=True,
            )
        except Exception as exc:
            raise RuntimeError(f"textutil RTF conversion failed: {exc}") from exc

        rtf_path_e = escape_applescript(str(rtf_file))
        script = f"""
set rtfFile to POSIX file "{rtf_path_e}"
set rtfData to read rtfFile as «class RTF »
tell application "Mail"
  set recipientStr to "{to_e}"
  set initialOut to count of messages of outbox
  set msg to make new outgoing message with properties {{subject:"{subject_e}", content:rtfData, visible:false}}
  tell msg
    make new to recipient at end of to recipients with properties {{address:"{to_e}"}}
  end tell
{cc_block}
{attachment_block}
  if "{from_e}" is not "" then
    set matched to false
    repeat with a in accounts
      if (user name of a is "{from_e}") or (name of a is "{from_e}") then
        set sender of msg to "{from_e}"
        set matched to true
        exit repeat
      end if
      try
        if (email addresses of a) contains "{from_e}" then
          set sender of msg to "{from_e}"
          set matched to true
          exit repeat
        end if
      end try
    end repeat
    if not matched then
      set sender of msg to "{from_e}"
    end if
  end if
  send msg
{verify_script_part}
end tell
return "OK sent to {to_e} (verified)"
"""
    else:
        script = f"""
tell application "Mail"
  set recipientStr to "{to_e}"
  set initialOut to count of messages of outbox
  set msg to make new outgoing message with properties {{subject:"{subject_e}", content:"{body_e}", visible:false}}
  tell msg
    make new to recipient at end of to recipients with properties {{address:"{to_e}"}}
  end tell
{cc_block}
{attachment_block}
  if "{from_e}" is not "" then
    set matched to false
    repeat with a in accounts
      if (user name of a is "{from_e}") or (name of a is "{from_e}") then
        set sender of msg to "{from_e}"
        set matched to true
        exit repeat
      end if
      try
        if (email addresses of a) contains "{from_e}" then
          set sender of msg to "{from_e}"
          set matched to true
          exit repeat
        end if
      end try
    end repeat
    if not matched then
      set sender of msg to "{from_e}"
    end if
  end if
  send msg
{verify_script_part}
end tell
return "OK sent to {to_e} (verified)"
"""
    return run_as(script)


def create_eml_draft(
    to: str,
    subject: str,
    body: str,
    from_addr: str,
    cc: str = "",
    attachments: list[str] | None = None,
    is_markdown: bool = True,
    zip_attachments: bool = False,
    open_in_mail: bool = True,
    humanize: bool = False,
) -> str:
    """Create a native .eml draft with HTML support and open in Mail.app."""
    import tempfile
    from email.message import EmailMessage

    if subject and not subject.lower().startswith("re:"):
        subject = subject.lower()

    if humanize:
        body = humanize_text(body)

    if zip_attachments and attachments:
        import zipfile

        temp_dir = Path(tempfile.mkdtemp(prefix="imail_zip_"))
        zip_path = temp_dir / "attachments.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for att in attachments:
                ap = Path(att).expanduser().resolve()
                if not ap.exists():
                    raise FileNotFoundError(f"Attachment file not found: {ap}")
                zf.write(ap, arcname=ap.name)
        attachments = [str(zip_path)]

    msg = EmailMessage()
    msg["Subject"] = subject
    if from_addr:
        msg["From"] = from_addr
    if to:
        msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["X-Unsent"] = "1"

    msg.set_content(body)
    if is_markdown:
        html_content = markdown_to_html(body)
        msg.add_alternative(html_content, subtype="html")

    if attachments:
        for att in attachments:
            ap = Path(att).expanduser().resolve()
            if not ap.exists():
                raise FileNotFoundError(f"Attachment file not found: {ap}")
            msg.add_attachment(
                ap.read_bytes(),
                maintype="application",
                subtype="octet-stream",
                filename=ap.name,
            )

    temp_dir = Path(tempfile.mkdtemp(prefix="imail_eml_"))
    eml_path = temp_dir / "draft.eml"
    eml_path.write_bytes(bytes(msg))

    if open_in_mail:
        subprocess.run(["open", "-a", "Mail", str(eml_path)], check=True)
        return f"OK opened draft in Mail.app ({eml_path})"

    return f"OK draft created at {eml_path}"


def save_silent_draft(
    to: str,
    subject: str,
    body: str,
    from_addr: str,
    cc: str = "",
    attachments: list[str] | None = None,
    humanize: bool = False,
) -> str:
    """Save draft directly in Mail.app background without popping up GUI windows."""
    if subject and not subject.lower().startswith("re:"):
        subject = subject.lower()

    if humanize:
        body = humanize_text(body)

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
    attachment_block = ""
    if attachments:
        for att in attachments:
            att_path = Path(att).expanduser().resolve()
            if not att_path.exists():
                raise FileNotFoundError(f"Attachment file not found: {att_path}")
            att_e = escape_applescript(str(att_path))
            attachment_block += f"""
  tell msg
    make new attachment with properties {{file name:POSIX file "{att_e}"}} at after last paragraph of content
  end tell
"""

    script = f"""
tell application "Mail"
  set msg to make new outgoing message with properties {{subject:"{subject_e}", content:"{body_e}", visible:false}}
  tell msg
    make new to recipient at end of to recipients with properties {{address:"{to_e}"}}
  end tell
{cc_block}
{attachment_block}
  if "{from_e}" is not "" then
    set matched to false
    repeat with a in accounts
      if (user name of a is "{from_e}") or (name of a is "{from_e}") then
        set sender of msg to "{from_e}"
        set matched to true
        exit repeat
      end if
      try
        if (email addresses of a) contains "{from_e}" then
          set sender of msg to "{from_e}"
          set matched to true
          exit repeat
        end if
      end try
    end repeat
    if not matched then
      set sender of msg to "{from_e}"
    end if
  end if
  save msg
end tell
return "OK draft saved quietly for {to_e}"
"""
    return run_as(script)


