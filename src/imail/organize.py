"""Inbox organization — MOVE only, never delete."""

from __future__ import annotations

import re
import sys
from typing import TextIO

from imail.mail import load_accounts_config, run_as

FOLDERS = [
    "Action",
    "Waiting",
    "Meetings",
    "IT",
    "Releases",
    "Security",
    "FYI",
    "Personal",
    "Archive",
    "Job Applications",
]

RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "Security",
        re.compile(
            r"leaked secrets|phishing|security alert|infosec|suspicious|"
            r"unusual (sign[- ]?in|activity)|verify your (email|account|new device)|2[- ]?factor|"
            r"\[GitHub\].*(sudo|passkey|SSH|OAuth|email address|identity)|"
            r"New sign-in detected|verification code|"
            r"taken ownership of your team's",
            re.I,
        ),
    ),
    (
        "Meetings",
        re.compile(
            r"^(Accepted|Declined|Canceled|Cancelled|Tentative|New Time Proposed):|"
            r"^Invitation:|Webex meeting|Zoom (Meeting|Link)|Google Meet|"
            r"Weekly Meeting|AI Champion Club|knowledge Sharing Sessions|"
            r"Brown Bag|huddle|calendar invite",
            re.I,
        ),
    ),
    (
        "IT",
        re.compile(
            r"ITSUPPORT-|IT Notification|Egnyte|SharePoint|Planned Maintenance|"
            r"IT Notice|Microsoft 365|Metabase Login|Github Copilot|GitHub Copilot|"
            r"Claude (Premium|Console|API)|OpenRouter|API (Key|token)|Case #:"
            r"|Connect Exchange|Snowflake Dev Day|AigisQuery",
            re.I,
        ),
    ),
    (
        "Releases",
        re.compile(
            r"\bWINT\b|WINT_|CROWD_|Internal release|Release \d|"
            r"Pull request #\d|[- ]Pull request #",
            re.I,
        ),
    ),
    (
        "Job Applications",
        re.compile(
            r"\b(W2|C2C|contract)\b|Right to Represent|job might be right|"
            r"Opportunity for|Urgent Opening|Opening--|Interview Request|"
            r"thank you for your application|Handshake AI|New bounty:|"
            r"Software Developer--|Full Stack|QA Tester|Lab Technician|"
            r"based in Sunnyvale|Onsite Role|"
            r"LinkedIn Job Alerts|via LinkedIn|just messaged you|"
            r"inmail-hit-reply|messages-noreply@linkedin|"
            r"messaging-digest-noreply|jobalerts-noreply|"
            r"Career Opportunity|GenAI |AI Engineer|Staff Full-Stack|"
            r"joinhandshake|Handshake <|Outlier Team|SME Careers|"
            r"hire\.lever\.co|JumpCloud|accept the invite|"
            r"top applicant|Projects ready for you",
            re.I,
        ),
    ),
    (
        "Personal",
        re.compile(
            r"Medical Records|FasTrak|401\(k\)|gift card|award envelop|"
            r"Holiday|Birthday|Venmo|domain contact|health summary|care team|"
            r"Telehealth|YouTube Premium|Apple Card|PayPal|Chai Tides|"
            r"Men's Group|polarisprovisions|Refund update|Your refund|"
            r"^(Shipped|Delivered|Ordered|Delivery update):|"
            r"Nutrition & Wellness|exclusive, limited-time|"
            r"W2\s*/\s*1099|Form 1099|1099-NEC|tax deadline|"
            r"Alumni email activity|Xlab Alumni|briopedia.*archive|"
            r"thepersonalprofessor\.org|Robinhood Markets Consolidated",
            re.I,
        ),
    ),
    (
        "Action",
        re.compile(
            r"Missing Property|action required|can we deploy|Please (reply|help|Resend)|"
            r"Request for Review|Request to Raise|Request for \$|"
            r"please prepare|needs? your",
            re.I,
        ),
    ),
    (
        "FYI",
        re.compile(
            r"weekly update|newsletter|Welcome To|New sign-in|Your receipt|"
            r"order confirmation|promotion|shipping|DocuSign|Looking for new role|"
            r"startup|coffee!|Ca phe|Verify your|Failed production deployment|"
            r"Turn Up the Heat|Still Time to Vote|free.*Support|Activate your|"
            r"Upcoming changes|joined your Linear|receipt from|"
            r"Amazon Gift Card|supporting docs|workflow document|"
            r"Notes from UI|Scaling AI|AI API Keys|AI knowledge",
            re.I,
        ),
    ),
]


def classify(subj: str, folders_available: set[str], sender: str = "") -> str | None:
    blob = f"{subj or ''}\n{sender or ''}"
    for folder, pat in RULES:
        if pat.search(blob):
            if folder in folders_available:
                return folder
            if folder == "Job Applications" and "FYI" in folders_available:
                return "FYI"
            if "FYI" in folders_available:
                return "FYI"
            return None
    return None


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


def list_mailbox_names(acct_name: str) -> set[str]:
    out = run_as(
        f"""
tell application "Mail"
  set acct to first account whose name is "{acct_name}"
  set out to ""
  repeat with b in mailboxes of acct
    set out to out & (name of b) & linefeed
  end repeat
  return out
end tell
"""
    )
    return {line.strip() for line in out.splitlines() if line.strip()}


def inbox_name(boxes: set[str]) -> str | None:
    for cand in ("INBOX", "Inbox", "inbox"):
        if cand in boxes:
            return cand
    return None


def ensure_folders(acct_name: str, existing: set[str]) -> set[str]:
    for fname in FOLDERS:
        if fname in existing:
            continue
        script = f"""
tell application "Mail"
  set acct to first account whose name is "{acct_name}"
  try
    make new mailbox with properties {{name:"{fname}"}} at end of acct
  end try
end tell
"""
        try:
            run_as(script)
            existing.add(fname)
        except Exception:
            pass
    return existing


def fetch_subjects(acct_name: str, inbox: str, limit: int) -> list[tuple[int, str, str]]:
    # Coerce subject/sender safely — some Gmail/IMAP messages throw -1700 on raw subject.
    # Fields: index <tab> subject <unit sep> sender
    script = f"""
tell application "Mail"
  set acct to first account whose name is "{acct_name}"
  set box to mailbox "{inbox}" of acct
  set msgs to messages of box
  set n to count of msgs
  if n > {limit} then set n to {limit}
  set out to ""
  set US to character id 31
  repeat with i from 1 to n
    set m to item i of msgs
    set subjText to ""
    set senderText to ""
    try
      set subjText to (subject of m) as text
    on error
      try
        set subjText to (subject of m as string)
      on error
        set subjText to ""
      end try
    end try
    try
      set senderText to (sender of m) as text
    on error
      set senderText to ""
    end try
    set out to out & i & tab & subjText & US & senderText & linefeed
  end repeat
  return out
end tell
"""
    out = run_as(script)
    rows: list[tuple[int, str, str]] = []
    for line in out.splitlines():
        if "\t" not in line:
            continue
        idx_s, rest = line.split("\t", 1)
        if "\x1f" in rest:
            subj, sender = rest.split("\x1f", 1)
        else:
            subj, sender = rest, ""
        try:
            rows.append((int(idx_s), subj, sender))
        except ValueError:
            continue
    return rows


def move_index(acct_name: str, inbox: str, index: int, dest: str) -> None:
    script = f"""
tell application "Mail"
  set acct to first account whose name is "{acct_name}"
  set box to mailbox "{inbox}" of acct
  set m to item {index} of (messages of box)
  set destBox to mailbox "{dest}" of acct
  move m to destBox
end tell
"""
    run_as(script)


def resolve_account_alias(name: str) -> str:
    config = load_accounts_config()
    aliases = config.get("aliases", {})
    key = name.lower()
    if name in aliases:
        return aliases[name]
    if key in aliases:
        return aliases[key]
    return name


def organize_inboxes(
    account: str | None = None,
    limit: int = 200,
    out: TextIO | None = None,
) -> int:
    stream = out or sys.stdout
    only = resolve_account_alias(account) if account else None
    accounts = list_accounts()
    if only:
        accounts = [
            (acct_name, user)
            for acct_name, user in accounts
            if acct_name == only
            or user.lower() == only.lower()
            or acct_name.lower() == only.lower()
        ]
        if not accounts:
            print(f"FAIL: no account matching {only!r}", file=sys.stderr)
            print(
                "known: " + ", ".join(f"{n}|{u}" for n, u in list_accounts()),
                file=sys.stderr,
            )
            return 2
    print(f"accounts={len(accounts)} limit_per_inbox={limit}", file=stream)
    for acct_name, user in accounts:
        print(f"== {acct_name} | {user}", file=stream)
        try:
            boxes = list_mailbox_names(acct_name)
        except Exception as exc:
            print(f"  SKIP boxes: {exc}", file=stream)
            continue
        boxes = ensure_folders(acct_name, boxes)
        inbox = inbox_name(boxes)
        if not inbox:
            print("  SKIP: no Inbox/INBOX", file=stream)
            continue
        try:
            rows = fetch_subjects(acct_name, inbox, limit)
        except Exception as exc:
            print(f"  SKIP fetch: {exc}", file=stream)
            continue
        plans = [
            (idx, classify(subj, boxes, sender=sender), subj[:70])
            for idx, subj, sender in rows
        ]
        plans = [(idx, dest, subj) for idx, dest, subj in plans if dest]
        plans.sort(key=lambda item: -item[0])
        moved = 0
        fails = 0
        for idx, dest, _subj in plans:
            try:
                move_index(acct_name, inbox, idx, dest)
                moved += 1
            except Exception as exc:
                fails += 1
                if fails <= 3:
                    print(f"  FAIL move {idx}→{dest}: {exc}", file=stream)
        print(
            f"  inbox={inbox} scanned={len(rows)} matched={len(plans)} moved={moved}",
            file=stream,
        )
    print("OK — nothing deleted", file=stream)
    return 0
