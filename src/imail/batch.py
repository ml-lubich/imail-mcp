"""Queue, status, and batch sending utilities for imail."""

from __future__ import annotations

import json
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from imail import mail

DEFAULT_QUEUE_DIR = Path.home() / ".imail"
DEFAULT_QUEUE_FILE = DEFAULT_QUEUE_DIR / "queue.json"


@dataclass
class QueueItem:
    id: str
    from_addr: str
    to: str
    subject: str
    body: str
    cc: str = ""
    attachments: list[str] | None = None
    markdown: bool = True
    zip_attachments: bool = False
    humanize: bool = False
    status: str = "pending"  # pending, sent, failed
    error: str = ""
    created_at: float = 0.0
    sent_at: float = 0.0


def ensure_queue_dir(queue_path: Path = DEFAULT_QUEUE_FILE) -> None:
    queue_path.parent.mkdir(parents=True, exist_ok=True)


def load_queue(queue_path: Path = DEFAULT_QUEUE_FILE) -> list[dict[str, Any]]:
    if not queue_path.exists():
        return []
    try:
        data = json.loads(queue_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def save_queue(items: list[dict[str, Any]], queue_path: Path = DEFAULT_QUEUE_FILE) -> None:
    ensure_queue_dir(queue_path)
    queue_path.write_text(json.dumps(items, indent=2), encoding="utf-8")


def enqueue_items(
    items: list[dict[str, Any]],
    queue_path: Path = DEFAULT_QUEUE_FILE,
) -> int:
    """Add items to queue. Returns number of new items added."""
    current = load_queue(queue_path)
    existing_ids = {x.get("id") for x in current if "id" in x}
    added = 0
    now = time.time()
    for item in items:
        item_id = item.get("id") or f"{item.get('to')}_{int(now*1000)}_{random.randint(100, 999)}"
        if item_id not in existing_ids:
            new_item = {
                "id": item_id,
                "from_addr": item.get("from_addr", ""),
                "to": item.get("to", ""),
                "subject": item.get("subject", ""),
                "body": item.get("body", ""),
                "cc": item.get("cc", ""),
                "attachments": item.get("attachments") or [],
                "markdown": item.get("markdown", True),
                "zip_attachments": item.get("zip_attachments", False),
                "humanize": item.get("humanize", False),
                "status": "pending",
                "error": "",
                "created_at": now,
                "sent_at": 0.0,
            }
            current.append(new_item)
            existing_ids.add(item_id)
            added += 1
    save_queue(current, queue_path)
    return added


def clear_queue(queue_path: Path = DEFAULT_QUEUE_FILE, status_filter: str | None = None) -> int:
    """Clear items from queue. If status_filter given, only clear matching."""
    current = load_queue(queue_path)
    if status_filter:
        remaining = [x for x in current if x.get("status") != status_filter]
        cleared = len(current) - len(remaining)
        save_queue(remaining, queue_path)
        return cleared
    save_queue([], queue_path)
    return len(current)


def get_queue_summary(queue_path: Path = DEFAULT_QUEUE_FILE) -> dict[str, int]:
    current = load_queue(queue_path)
    summary = {"total": len(current), "pending": 0, "sent": 0, "failed": 0}
    for item in current:
        st = item.get("status", "pending")
        if st in summary:
            summary[st] += 1
        else:
            summary[st] = 1
    return summary


def run_batch_dispatch(
    queue_path: Path = DEFAULT_QUEUE_FILE,
    limit: int | None = None,
    min_delay: float = 1.0,
    max_delay: float = 3.0,
    dry_run: bool = False,
    progress_callback: Callable[[dict[str, Any], int, int], None] | None = None,
) -> dict[str, int]:
    """Process pending items in queue with randomized delay jitter."""
    items = load_queue(queue_path)
    pending_indices = [idx for idx, item in enumerate(items) if item.get("status") == "pending"]
    if limit is not None and limit > 0:
        pending_indices = pending_indices[:limit]

    stats = {"processed": 0, "sent": 0, "failed": 0}
    total_to_process = len(pending_indices)

    for step, idx in enumerate(pending_indices, start=1):
        item = items[idx]
        stats["processed"] += 1

        if dry_run:
            item["status"] = "dry_run"
            stats["sent"] += 1
            if progress_callback:
                progress_callback(item, step, total_to_process)
            continue

        try:
            mail.send_message(
                to=item["to"],
                subject=item["subject"],
                body=item["body"],
                from_addr=item["from_addr"],
                cc=item.get("cc", ""),
                attachments=item.get("attachments") or None,
                is_markdown=item.get("markdown", True),
                zip_attachments=item.get("zip_attachments", False),
                humanize=item.get("humanize", False),
            )
            item["status"] = "sent"
            item["sent_at"] = time.time()
            item["error"] = ""
            stats["sent"] += 1
        except Exception as exc:
            item["status"] = "failed"
            item["error"] = str(exc)
            stats["failed"] += 1

        save_queue(items, queue_path)

        if progress_callback:
            progress_callback(item, step, total_to_process)

        if step < total_to_process:
            delay = random.uniform(min_delay, max_delay)
            time.sleep(delay)

    return stats
