"""Auto-drafting and intelligent reply pipeline for imail.

Analyzes inbox messages, filters spam/automated newsletters, identifies emails
requiring response, matches appropriate attachments (e.g. resumes), and creates
silent drafts in Mail.app with zero markdown, casual human voice, and no GUI popups.
Auto-sends only on ultra-high confidence / trivial low-stakes confirmations.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from imail.mail import (
    load_accounts_config,
    save_silent_draft,
    send_message,
)

SEEN_PATH = Path.home() / ".config" / "imail" / "autodraft-seen.json"
DEFAULT_PERSONAL = [
    "michaelle.lubich@gmail.com",
    "metropol007@gmail.com",
    "misha@lupfr.com",
]

SKIP_SENDER_PATTERNS = [
    re.compile(r"no[-_]?reply", re.I),
    re.compile(r"notification", re.I),
    re.compile(r"newsletter", re.I),
    re.compile(r"mailer-daemon", re.I),
    re.compile(r"donotreply", re.I),
    re.compile(r"billing@", re.I),
    re.compile(r"support@", re.I),
    re.compile(r"updates?@", re.I),
    re.compile(r"alert[s]?@", re.I),
    re.compile(r"marketing@", re.I),
    re.compile(r"digest@", re.I),
    re.compile(r"invitations?@", re.I),
    re.compile(r"automated@", re.I),
    re.compile(r"@substack\.com$", re.I),
    re.compile(r"@github\.com$", re.I),
    re.compile(r"@linkedin\.com$", re.I),
    re.compile(r"@medium\.com$", re.I),
    re.compile(r"@twitter\.com$", re.I),
    re.compile(r"@x\.com$", re.I),
    re.compile(r"@quora\.com$", re.I),
]

SKIP_SUBJECT_PATTERNS = [
    re.compile(r"verification code|security alert|sign-in detected", re.I),
    re.compile(r"your (order|receipt|invoice|statement|subscription|refund)", re.I),
    re.compile(r"newsletter|digest|weekly round|announcing|unsubscribed", re.I),
    re.compile(r"^(shipped|delivered|ordered):", re.I),
]

# Mass-mail / generic staffing blasts — never draft, never send.
BLAST_SUBJECT_PATTERNS = [
    re.compile(r"OPENING FOR"),
    re.compile(r":::"),
    re.compile(r"\[ONSITE\]", re.I),
    re.compile(r"IMMEDIATE INTERVIEW", re.I),
    re.compile(r"URGENT\s*(\|\||HIRING)", re.I),
    re.compile(r"^Direct Client:", re.I),
]

INTENT_SKIP = "skip"
INTENT_RECRUITER = "recruiter"
INTENT_DIRECT_INQUIRY = "direct_inquiry"
INTENT_CONFIRMATION = "confirmation"

MARKDOWN_PATTERNS = [
    (re.compile(r"\*\*(.*?)\*\*"), r"\1"),
    (re.compile(r"\*(.*?)\*"), r"\1"),
    (re.compile(r"__(.*?)__"), r"\1"),
    (re.compile(r"_(.*?)_"), r"\1"),
    (re.compile(r"`(.*?)`"), r"\1"),
    (re.compile(r"^#+\s*", re.M), ""),
    (re.compile(r"\[(.*?)\]\((.*?)\)"), r"\1 (\2)"),
    (re.compile(r"[—–]"), "-"),
]


def strip_markdown(text: str) -> str:
    """Ensure plain human email formatting without markdown artifacts."""
    for pattern, repl in MARKDOWN_PATTERNS:
        text = pattern.sub(repl, text)
    return text.strip()


def human_voice(text: str) -> str:
    """Misha's send voice: lowercase, short, no analogies, no markdown."""
    return strip_markdown(text).lower()


def classify_intent(sender: str, subject: str, snippet: str = "") -> str:
    """Classify the intent of an incoming email."""
    for pat in SKIP_SENDER_PATTERNS:
        if pat.search(sender):
            return INTENT_SKIP

    for pat in SKIP_SUBJECT_PATTERNS:
        if pat.search(subject):
            return INTENT_SKIP

    for pat in BLAST_SUBJECT_PATTERNS:
        if pat.search(subject):
            return INTENT_SKIP

    text = f"{subject} {snippet}".lower()

    if re.search(
        r"\b(sounds good|does that work|are you free|see you (tomorrow|then)|got it thanks)\b",
        text,
    ):
        return INTENT_CONFIRMATION

    if re.search(
        r"contract|opening|role|job|engineer|developer|recruit|w2|c2c|salary|rate|opportunity",
        text,
    ):
        return INTENT_RECRUITER

    if re.search(r"\?|when|how|where|update|status|discuss|talk", text):
        return INTENT_DIRECT_INQUIRY

    return INTENT_SKIP


def select_resume(job_text: str) -> str | None:
    """Select the best matching resume PDF and return a clean path without internal suffixes."""
    resumes_dir = Path.home() / "dev/resumes/resumes"
    if not resumes_dir.exists():
        return None

    clean_dir = Path.home() / ".cache/imail/resumes"
    clean_dir.mkdir(parents=True, exist_ok=True)
    clean_path = clean_dir / "resume_mlubich.pdf"

    jt = job_text.lower()
    variant = "resume_mlubich"
    if "ai" in jt or "ml" in jt or "llm" in jt or "agent" in jt:
        variant = "resume_mlubich_ai"
    elif "fullstack" in jt or "full stack" in jt:
        variant = "resume_mlubich_fullstack_ai"
    elif "infra" in jt or "mlops" in jt or "devops" in jt:
        variant = "resume_mlubich_infra"
    elif "fde" in jt or "forward deployed" in jt:
        variant = "resume_mlubich_fde"
    elif "swe" in jt or "software engineer" in jt:
        variant = "resume_mlubich_swe"

    source_dir = resumes_dir / variant
    if source_dir.exists():
        pdfs = list(source_dir.glob("*.pdf"))
        if pdfs:
            shutil.copy2(pdfs[0], clean_path)
            return str(clean_path)

    base_dir = resumes_dir / "resume_mlubich"
    if base_dir.exists():
        pdfs = list(base_dir.glob("*.pdf"))
        if pdfs:
            shutil.copy2(pdfs[0], clean_path)
            return str(clean_path)

    return None


@dataclass
class DraftDecision:
    account: str
    recipient: str
    subject: str
    body: str
    attachments: list[str]
    intent: str
    auto_send: bool = False
    confidence: float = 0.5


def generate_draft_response(
    account: str,
    sender: str,
    subject: str,
    snippet: str = "",
    known_correspondent: bool = False,
) -> DraftDecision | None:
    """Generate a human-like, non-verbose, respectful draft response."""
    intent = classify_intent(sender, subject, snippet)
    if intent == INTENT_SKIP:
        return None

    match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", sender)
    recipient = match.group(0) if match else sender

    clean_subject = subject
    if not clean_subject.lower().startswith("re:"):
        clean_subject = f"Re: {clean_subject}"

    attachments: list[str] = []
    auto_send = False
    confidence = 0.5

    if intent == INTENT_RECRUITER:
        resume = select_resume(f"{subject} {snippet}")
        if resume:
            attachments.append(resume)
            body = (
                "hi,\n\n"
                "what made you reach out to me, and why did it seem like i was a good fit for this role?\n\n"
                "attached my resume.\n\n"
                "thanks,\n"
                "misha"
            )
        else:
            body = (
                "hi,\n\n"
                "what made you reach out to me, and why did it seem like i was a good fit for this role?\n\n"
                "thanks,\n"
                "misha"
            )
        confidence = 0.65

    elif intent == INTENT_CONFIRMATION:
        body = "sounds good, looking forward to it."
        if known_correspondent:
            auto_send = True
            confidence = 0.96
        else:
            confidence = 0.70

    elif intent == INTENT_DIRECT_INQUIRY:
        body = (
            "hi,\n\n"
            "thanks for following up. taking a look at this now and will get back to you shortly.\n\n"
            "thanks,\n"
            "misha"
        )
        confidence = 0.55

    else:
        return None

    body = human_voice(body)

    return DraftDecision(
        account=account,
        recipient=recipient,
        subject=clean_subject,
        body=body,
        attachments=attachments,
        intent=intent,
        auto_send=auto_send,
        confidence=confidence,
    )


def _normalize_subject(subject: str) -> str:
    text = subject.strip()
    while True:
        stripped = re.sub(r"^(re|fwd|fw)\s*:\s*", "", text, flags=re.I)
        if stripped == text:
            break
        text = stripped
    return re.sub(r"\s+", " ", text).strip().lower()


def _seen_key(account: str, recipient: str, subject: str) -> str:
    return f"{account}|{recipient.lower()}|{_normalize_subject(subject)}"


def _load_seen(path: Path | None = None) -> set[str]:
    target = path or SEEN_PATH
    if not target.exists():
        return set()
    try:
        data = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError):
        return set()
    if isinstance(data, list):
        return {str(x) for x in data}
    return set()


def _save_seen(keys: set[str], path: Path | None = None) -> None:
    target = path or SEEN_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sorted(keys)))


def _personal_accounts() -> list[str]:
    cfg = load_accounts_config()
    emails = cfg.get("walls", {}).get("personal", {}).get("emails", [])
    return [e for e in emails if e in DEFAULT_PERSONAL] or list(DEFAULT_PERSONAL)


def process_inbox_autodraft(
    accounts: list[str] | None = None,
    limit_per_account: int = 15,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Scan personal inboxes, evaluate unreplied emails, and create silent drafts."""
    from imail import mail

    target_accounts = accounts or _personal_accounts()
    results: list[dict[str, Any]] = []
    seen_recipients: set[str] = set()
    seen = _load_seen()

    for acct in target_accounts:
        try:
            messages = mail.list_messages(account=acct, mailbox="INBOX", limit=limit_per_account)
        except Exception as exc:
            results.append({"account": acct, "status": "error", "error": str(exc)})
            continue

        for msg in messages:
            sender = msg.get("sender", "")
            subject = msg.get("subject", "")
            snippet = msg.get("snippet", "")

            decision = generate_draft_response(
                account=acct,
                sender=sender,
                subject=subject,
                snippet=snippet,
            )

            if not decision or decision.recipient in seen_recipients:
                continue

            key = _seen_key(acct, decision.recipient, decision.subject)
            if key in seen:
                continue

            seen_recipients.add(decision.recipient)

            res_info = {
                "account": acct,
                "recipient": decision.recipient,
                "subject": decision.subject,
                "intent": decision.intent,
                "auto_send": decision.auto_send,
                "attachments": decision.attachments,
                "body": decision.body,
            }

            if not dry_run:
                if decision.auto_send and decision.confidence >= 0.95:
                    send_message(
                        to=decision.recipient,
                        subject=decision.subject,
                        body=decision.body,
                        from_addr=acct,
                        attachments=decision.attachments,
                        is_markdown=False,
                    )
                    res_info["status"] = "sent"
                else:
                    save_silent_draft(
                        to=decision.recipient,
                        subject=decision.subject,
                        body=decision.body,
                        from_addr=acct,
                        attachments=decision.attachments,
                    )
                    res_info["status"] = "drafted"
                seen.add(key)
                _save_seen(seen)
            else:
                res_info["status"] = "dry_run"

            results.append(res_info)

    return results
