"""Auto-drafting and intelligent reply pipeline for imail.

Analyzes inbox messages, filters spam/automated newsletters, identifies emails
requiring response, matches appropriate attachments (e.g. resumes), and creates
silent drafts in Mail.app with zero markdown, casual human voice, and no GUI popups.
Auto-sends only on ultra-high confidence / trivial low-stakes confirmations.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from imail.mail import (
    escape_applescript,
    load_accounts_config,
    run_as,
    save_silent_draft,
    send_message,
)

# Automated / spam senders and domains that should NEVER receive replies
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

# Automated / blast subjects that never require direct replies
SKIP_SUBJECT_PATTERNS = [
    re.compile(r"verification code|security alert|sign-in detected", re.I),
    re.compile(r"your (order|receipt|invoice|statement|subscription|refund)", re.I),
    re.compile(r"newsletter|digest|weekly round|announcing|unsubscribed", re.I),
    re.compile(r"^(shipped|delivered|ordered):", re.I),
]

# Intent classification types
INTENT_SKIP = "skip"
INTENT_RECRUITER = "recruiter"
INTENT_DIRECT_INQUIRY = "direct_inquiry"
INTENT_CONFIRMATION = "confirmation"

# Strip all markdown formatting to ensure natural, human-readable plain text
MARKDOWN_PATTERNS = [
    (re.compile(r"\*\*(.*?)\*\*"), r"\1"),  # bold **text**
    (re.compile(r"\*(.*?)\*"), r"\1"),      # italic *text*
    (re.compile(r"__(.*?)__"), r"\1"),      # bold __text__
    (re.compile(r"_(.*?)_"), r"\1"),        # italic _text_
    (re.compile(r"`(.*?)`"), r"\1"),        # inline code `code`
    (re.compile(r"^#+\s*", re.M), ""),      # headers # Header
    (re.compile(r"\[(.*?)\]\((.*?)\)"), r"\1 (\2)"), # markdown links
    (re.compile(r"[—–]"), "-"),             # em/en dashes
]


def strip_markdown(text: str) -> str:
    """Ensure plain human email formatting without markdown artifacts."""
    for pattern, repl in MARKDOWN_PATTERNS:
        text = pattern.sub(repl, text)
    return text.strip()


def classify_intent(sender: str, subject: str, snippet: str = "") -> str:
    """Classify the intent of an incoming email."""
    # Check sender exclusions
    for pat in SKIP_SENDER_PATTERNS:
        if pat.search(sender):
            return INTENT_SKIP

    # Check subject exclusions
    for pat in SKIP_SUBJECT_PATTERNS:
        if pat.search(subject):
            return INTENT_SKIP

    text = f"{subject} {snippet}".lower()

    # Recruiter outreach patterns
    if re.search(r"contract|opening|role|job|engineer|developer|recruit|w2|c2c|salary|rate|opportunity", text):
        return INTENT_RECRUITER

    # Direct short confirmation
    if re.search(r"sounds good|let me know|are you free|does that work|can you confirm|confirmation", text):
        return INTENT_CONFIRMATION

    # General direct inquiry
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

    # Fallback to base resume
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
) -> DraftDecision | None:
    """Generate a human-like, non-verbose, respectful draft response."""
    intent = classify_intent(sender, subject, snippet)
    if intent == INTENT_SKIP:
        return None

    # Determine recipient email address from sender string e.g. "Name <email@example.com>"
    match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", sender)
    recipient = match.group(0) if match else sender

    clean_subject = subject
    if not clean_subject.lower().startswith("re:"):
        clean_subject = f"Re: {clean_subject}"

    attachments: list[str] = []
    body = ""
    auto_send = False
    confidence = 0.5

    if intent == INTENT_RECRUITER:
        resume = select_resume(f"{subject} {snippet}")
        if resume:
            attachments.append(resume)
            body = (
                "Hi,\n\n"
                "What made you reach out to me, and why did it seem like I was a good fit for this role?\n\n"
                "I've attached my resume for your review as well.\n\n"
                "Thanks,\n"
                "Misha"
            )
        else:
            body = (
                "Hi,\n\n"
                "What made you reach out to me, and why did it seem like I was a good fit for this role?\n\n"
                "Thanks,\n"
                "Misha"
            )
        confidence = 0.65

    elif intent == INTENT_CONFIRMATION:
        body = "Sounds good, looking forward to it."
        confidence = 0.70

    elif intent == INTENT_DIRECT_INQUIRY:
        body = (
            "Hi,\n\n"
            "Thanks for following up. Taking a look at this now and will get back to you shortly.\n\n"
            "Thanks,\n"
            "Misha"
        )
        confidence = 0.55

    body = strip_markdown(body)

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


def process_inbox_autodraft(
    accounts: list[str] | None = None,
    limit_per_account: int = 15,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Scan personal inboxes, evaluate unreplied emails, and create silent drafts."""
    cfg = load_accounts_config()
    personal_accounts = cfg.get("walls", {}).get("personal", {}).get("emails", [])

    target_accounts = accounts or personal_accounts
    results: list[dict[str, Any]] = []
    seen_recipients: set[str] = set()

    for acct in target_accounts:
        try:
            # We query Mail.app via imail list
            from imail import mail
            messages = mail.list_messages(account=acct, mailbox="INBOX", limit=limit_per_account)
            for msg in messages:
                sender = msg.get("sender", "")
                subject = msg.get("subject", "")

                decision = generate_draft_response(
                    account=acct,
                    sender=sender,
                    subject=subject,
                )

                if not decision or decision.recipient in seen_recipients:
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
                else:
                    res_info["status"] = "dry_run"

                results.append(res_info)
        except Exception as e:
            # Keep processing remaining accounts
            continue

    return results
