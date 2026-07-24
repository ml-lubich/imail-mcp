#!/usr/bin/env python3
"""Organize INBOX across ALL Mail.app accounts. MOVE only — never delete."""
from __future__ import annotations

import re
import subprocess
import sys

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

# (folder, pattern) — first match wins
RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "Security",
        re.compile(
            r"leaked secrets|phishing|security alert|infosec|suspicious|"
            r"unusual (sign[- ]?in|activity)|verify your (email|account)|2[- ]?factor",
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
            r"based in Sunnyvale|Onsite Role",
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
            r"Nutrition & Wellness|exclusive, limited-time",
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


def classify(subj: str, folders_available: set[str]) -> str | None:
    for folder, pat in RULES:
        if pat.search(subj or ""):
            if folder in folders_available:
                return folder
            # Job Applications → FYI if missing
            if folder == "Job Applications" and "FYI" in folders_available:
                return "FYI"
            if "FYI" in folders_available:
                return "FYI"
            return None
    return None


def run_as(script: str) -> str:
    r = subprocess.run(["osascript"], input=script, text=True, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "osascript failed").strip())
    return (r.stdout or "").strip()


def list_accounts() -> list[tuple[str, str]]:
    out = run_as(
        '''
tell application "Mail"
  set out to ""
  repeat with a in accounts
    set out to out & (name of a) & tab & (user name of a) & linefeed
  end repeat
  return out
end tell
'''
    )
    rows = []
    for line in out.splitlines():
        if "\t" in line:
            name, user = line.split("\t", 1)
            rows.append((name.strip(), user.strip()))
    return rows


def list_mailbox_names(acct_name: str) -> set[str]:
    out = run_as(
        f'''
tell application "Mail"
  set acct to first account whose name is "{acct_name}"
  set out to ""
  repeat with b in mailboxes of acct
    set out to out & (name of b) & linefeed
  end repeat
  return out
end tell
'''
    )
    return {ln.strip() for ln in out.splitlines() if ln.strip()}


def inbox_name(boxes: set[str]) -> str | None:
    for cand in ("INBOX", "Inbox", "inbox"):
        if cand in boxes:
            return cand
    return None


def ensure_folders(acct_name: str, existing: set[str]) -> set[str]:
    for fname in FOLDERS:
        if fname in existing:
            continue
        # Don't create Job Applications on Exchange unless useful — skip auto-create for that
        if fname == "Job Applications":
            continue
        script = f'''
tell application "Mail"
  set acct to first account whose name is "{acct_name}"
  try
    make new mailbox with properties {{name:"{fname}"}} at end of acct
  end try
end tell
'''
        try:
            run_as(script)
            existing.add(fname)
        except Exception:
            pass
    return existing


def fetch_subjects(acct_name: str, inbox: str, limit: int) -> list[tuple[int, str]]:
    script = f'''
tell application "Mail"
  set acct to first account whose name is "{acct_name}"
  set box to mailbox "{inbox}" of acct
  set msgs to messages of box
  set n to count of msgs
  if n > {limit} then set n to {limit}
  set out to ""
  repeat with i from 1 to n
    set m to item i of msgs
    set out to out & i & tab & (subject of m) & linefeed
  end repeat
  return out
end tell
'''
    out = run_as(script)
    rows = []
    for line in out.splitlines():
        if "\t" not in line:
            continue
        idx_s, subj = line.split("\t", 1)
        try:
            rows.append((int(idx_s), subj))
        except ValueError:
            continue
    return rows


def move_index(acct_name: str, inbox: str, index: int, dest: str) -> None:
    script = f'''
tell application "Mail"
  set acct to first account whose name is "{acct_name}"
  set box to mailbox "{inbox}" of acct
  set m to item {index} of (messages of box)
  set destBox to mailbox "{dest}" of acct
  move m to destBox
end tell
'''
    run_as(script)


ALIASES = {
    "google": "Google",
    "michaelle": "Google",
    "michaelle.lubich@gmail.com": "Google",
    "polaris": "Exchange",
    "exchange": "Exchange",
    "work": "Exchange",
    "metropol": "metropol007@gmail.com",
    "metropol007@gmail.com": "metropol007@gmail.com",
    "lupfr": "misha@lupfr.com",
    "misha@lupfr.com": "misha@lupfr.com",
}


def main() -> int:
    limit = 200
    only: str | None = None
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i] == "--limit" and i + 1 < len(argv):
            limit = int(argv[i + 1])
            i += 2
        elif argv[i] == "--account" and i + 1 < len(argv):
            only = ALIASES.get(argv[i + 1].lower(), argv[i + 1])
            # also try exact key
            if argv[i + 1] in ALIASES:
                only = ALIASES[argv[i + 1]]
            elif argv[i + 1].lower() in ALIASES:
                only = ALIASES[argv[i + 1].lower()]
            else:
                only = argv[i + 1]
            i += 2
        else:
            i += 1
    accounts = list_accounts()
    if only:
        accounts = [
            (n, u)
            for n, u in accounts
            if n == only or u.lower() == only.lower() or n.lower() == only.lower()
        ]
        if not accounts:
            print(f"FAIL: no account matching {only!r}", file=sys.stderr)
            print("known:", ", ".join(f"{n}|{u}" for n, u in list_accounts()), file=sys.stderr)
            return 2
    print(f"accounts={len(accounts)} limit_per_inbox={limit}")
    for acct_name, user in accounts:
        print(f"== {acct_name} | {user}")
        try:
            boxes = list_mailbox_names(acct_name)
        except Exception as e:
            print(f"  SKIP boxes: {e}")
            continue
        boxes = ensure_folders(acct_name, boxes)
        inbox = inbox_name(boxes)
        if not inbox:
            print("  SKIP: no Inbox/INBOX")
            continue
        try:
            rows = fetch_subjects(acct_name, inbox, limit)
        except Exception as e:
            print(f"  SKIP fetch: {e}")
            continue
        plans = [(idx, classify(subj, boxes), subj[:70]) for idx, subj in rows]
        plans = [(idx, dest, s) for idx, dest, s in plans if dest]
        plans.sort(key=lambda x: -x[0])
        moved = 0
        fails = 0
        for idx, dest, s in plans:
            try:
                move_index(acct_name, inbox, idx, dest)
                moved += 1
            except Exception as e:
                fails += 1
                if fails <= 3:
                    print(f"  FAIL move {idx}→{dest}: {e}")
        print(f"  inbox={inbox} scanned={len(rows)} matched={len(plans)} moved={moved}")
    print("OK — nothing deleted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
