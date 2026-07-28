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


def markdown_to_html(md: str) -> str:
    """Convert markdown text to clean, uniform Gmail-style Sans Serif HTML."""
    raw_html = ""
    try:
        from markdown_it import MarkdownIt

        raw_html = MarkdownIt().render(md)
    except Exception:
        import html
        import re

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
                text = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", text)
                text = re.sub(r"\*(.*?)\*", r"<em>\1</em>", text)
                text = re.sub(r"`(.*?)`", r"<code>\1</code>", text)
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
    font-size: 13px !important;
    background-color: #f1f3f4 !important;
    padding: 2px 4px !important;
    border-radius: 3px !important;
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
    - Occasional lowercase 'i' or uncapitalized initial sentence letters.
    - Occasional omitted trailing period at paragraph end.
    """
    import random
    import re

    # 1. Strip all emojis
    text = re.sub(r"[\U00010000-\U0010ffff\u2600-\u26FF\u2700-\u27BF]", "", text)

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
    is_markdown: bool = False,
    zip_attachments: bool = False,
    humanize: bool = False,
) -> str:
    if humanize:
        body = humanize_text(body)
        if subject:
            subject = subject.lower()

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
  set msg to make new outgoing message with properties {{subject:"{subject_e}", content:rtfData, visible:false}}
  tell msg
    make new to recipient at end of to recipients with properties {{address:"{to_e}"}}
  end tell
{cc_block}
{attachment_block}
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
    else:
        script = f"""
tell application "Mail"
  set msg to make new outgoing message with properties {{subject:"{subject_e}", content:"{body_e}", visible:false}}
  tell msg
    make new to recipient at end of to recipients with properties {{address:"{to_e}"}}
  end tell
{cc_block}
{attachment_block}
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


def create_eml_draft(
    to: str,
    subject: str,
    body: str,
    from_addr: str,
    cc: str = "",
    attachments: list[str] | None = None,
    is_markdown: bool = False,
    zip_attachments: bool = False,
    open_in_mail: bool = True,
    humanize: bool = False,
) -> str:
    """Create a native .eml draft with HTML support and open in Mail.app."""
    import tempfile
    from email.message import EmailMessage

    if humanize:
        body = humanize_text(body)
        if subject:
            subject = subject.lower()

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

