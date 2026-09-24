"""Typer CLI entry point for imail."""

from __future__ import annotations

import json

import typer

from imail import __version__
from imail import agent as agent_mod
from imail import mail
from imail import organize

app = typer.Typer(
    name="imail",
    help="Apple Mail.app CLI — agent-friendly, no IMAP/himalaya.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)

agent_app = typer.Typer(
    help="Agent introspection commands.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
app.add_typer(agent_app, name="agent")


@app.command("doctor")
def doctor_cmd() -> None:
    """Verify Mail.app is reachable."""
    try:
        mail.doctor()
        typer.echo("ok: Mail.app reachable")
        typer.echo(mail.format_accounts())
    except RuntimeError as exc:
        typer.echo(f"FAIL: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("accounts")
def accounts_cmd() -> None:
    """List Mail.app accounts."""
    try:
        typer.echo(mail.format_accounts())
    except RuntimeError as exc:
        typer.echo(f"FAIL: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("walls")
def walls_cmd() -> None:
    """Print work vs personal walls from accounts.json."""
    try:
        typer.echo(mail.format_walls())
    except FileNotFoundError as exc:
        typer.echo(f"FAIL: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("list")
def list_cmd(
    account: str = typer.Option("", "--account", help="Account name or email"),
    mailbox: str = typer.Option("INBOX", "--mailbox", help="Mailbox name"),
    limit: int = typer.Option(20, "--limit", help="Max messages"),
    as_json: bool = typer.Option(False, "--json", help="Output JSON"),
) -> None:
    """List inbox messages."""
    try:
        if as_json:
            rows = mail.list_messages(account=account, mailbox=mailbox, limit=limit)
            typer.echo(json.dumps(rows, indent=2))
        else:
            typer.echo(
                mail.format_list_messages(account=account, mailbox=mailbox, limit=limit)
            )
    except RuntimeError as exc:
        typer.echo(f"FAIL: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("organize")
def organize_cmd(
    account: str = typer.Option(
        "",
        "--account",
        "-a",
        help="Account alias: google, polaris, metropol, lupfr, etc.",
    ),
    limit: int = typer.Option(200, "--limit", "-n", help="Max messages per inbox"),
) -> None:
    """Organize INBOX across accounts (MOVE only — never delete)."""
    only = account or None
    code = organize.organize_inboxes(account=only, limit=limit)
    raise typer.Exit(code=code)


@app.command("autodraft")
def autodraft_cmd(
    account: str = typer.Option(
        "",
        "--account",
        "-a",
        help="Account email or alias (defaults to all personal walls)",
    ),
    limit: int = typer.Option(15, "--limit", "-n", help="Max messages per inbox"),
    dry_run: bool = typer.Option(False, "--dry-run", "--dry", help="Preview decisions without drafting"),
) -> None:
    """Scan personal inbox for messages needing reply, create silent drafts, or auto-send high-confidence."""
    from imail import autodraft
    accts = [account] if account else None
    results = autodraft.process_inbox_autodraft(accounts=accts, limit_per_account=limit, dry_run=dry_run)
    if not results:
        typer.echo("No pending messages requiring drafts.")
        return
    for item in results:
        typer.echo(f"[{item['status'].upper()}] ({item['account']}) -> {item['recipient']}: {item['subject']}")


@app.command("autodraft-eval")
def autodraft_eval_cmd() -> None:
    """Run the labeled autodraft eval against the real LLM and print a scorecard."""
    from imail import autodraft_eval

    cases = autodraft_eval.load_cases()
    results = autodraft_eval.run_eval(cases)
    typer.echo(autodraft_eval.format_eval_table(results))
    if any(r["unsafe_send"] for r in results):
        raise typer.Exit(code=1)


@app.command("autodraft-log")
def autodraft_log_cmd(
    n: int = typer.Option(20, "-n", "--limit", help="Number of recent decisions to show"),
) -> None:
    """Pretty-print the last N autodraft decisions from the log."""
    from imail import autodraft

    typer.echo(autodraft.format_recent_log(n))


@app.command("send")
def send_cmd(
    from_addr: str = typer.Option(..., "--from", help="Sender email (required wall)"),
    to: str = typer.Option(..., "--to", help="Recipient address"),
    subject: str = typer.Option(..., "--subject", help="Message subject"),
    body: str = typer.Option("", "--body", help="Message body string or path to body file"),
    body_file: str = typer.Option("", "--body-file", help="Path to body file"),
    cc: str = typer.Option("", "--cc", help="Optional CC address"),
    attach: list[str] = typer.Option(
        None,
        "--attach",
        "-a",
        help="Path to file attachment (can specify multiple times)",
    ),
    markdown: bool = typer.Option(
        True,
        "--markdown/--no-markdown",
        "-m/-M",
        help="Render HTML with Gmail Sans Serif (ON by default)",
    ),
    zip_attachments: bool = typer.Option(
        False,
        "--zip-attachments",
        "--zip",
        help="Bundle attachments into a single .zip archive",
    ),
    open_draft: bool = typer.Option(
        False,
        "--open",
        "-o",
        help="Open native HTML draft in Mail.app for review before sending",
    ),
    humanize: bool = typer.Option(
        False,
        "--humanize",
        "-H",
        help="Subtly humanize text (strip emojis, 5-10% natural typing touch, inspired by blader/humanizer)",
    ),
) -> None:
    """Send email via Mail.app."""
    try:
        from pathlib import Path

        body_text = body
        auto_md = False

        if body_file:
            bf_path = Path(body_file).expanduser().resolve()
            if not bf_path.is_file():
                raise RuntimeError(f"Body file not found: {body_file}")
            body_text = bf_path.read_text(encoding="utf-8")
            if bf_path.suffix.lower() in [".md", ".markdown"]:
                auto_md = True
        elif body:
            possible_file = Path(body).expanduser().resolve()
            if possible_file.is_file():
                body_text = possible_file.read_text(encoding="utf-8")
                if possible_file.suffix.lower() in [".md", ".markdown"]:
                    auto_md = True

        if not body_text:
            raise RuntimeError("Email body or body file is required")

        if open_draft:
            result = mail.create_eml_draft(
                to=to,
                subject=subject,
                body=body_text,
                from_addr=from_addr,
                cc=cc,
                attachments=attach,
                is_markdown=markdown or auto_md,
                zip_attachments=zip_attachments,
                open_in_mail=True,
                humanize=humanize,
            )
        else:
            result = mail.send_message(
                to=to,
                subject=subject,
                body=body_text,
                from_addr=from_addr,
                cc=cc,
                attachments=attach,
                is_markdown=markdown or auto_md,
                zip_attachments=zip_attachments,
                humanize=humanize,
            )
        typer.echo(result)
    except RuntimeError as exc:
        typer.echo(f"FAIL: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("draft")
def draft_cmd(
    to: str = typer.Option(..., "--to", "-t", help="Recipient email address"),
    subject: str = typer.Option(..., "--subject", "-s", help="Email subject line"),
    body: str = typer.Option("", "--body", "-b", help="Inline email body text"),
    body_file: str = typer.Option("", "--body-file", "-f", help="Path to body text/markdown file"),
    from_addr: str = typer.Option("", "--from", "-F", help="From email address / account name"),
    cc: str = typer.Option("", "--cc", "-c", help="CC email address"),
    attach: list[str] = typer.Option(None, "--attach", "-a", help="Attachment file path(s)"),
    humanize: bool = typer.Option(False, "--humanize", "-H", help="Subtly humanize text"),
) -> None:
    """Save a draft silently in Mail.app background without opening GUI windows."""
    try:
        from pathlib import Path

        body_text = body
        if body_file:
            bf_path = Path(body_file).expanduser().resolve()
            if not bf_path.is_file():
                raise RuntimeError(f"Body file not found: {body_file}")
            body_text = bf_path.read_text(encoding="utf-8")

        if not body_text:
            raise RuntimeError("Email body or body file is required")

        result = mail.save_silent_draft(
            to=to,
            subject=subject,
            body=body_text,
            from_addr=from_addr,
            cc=cc,
            attachments=attach,
            humanize=humanize,
        )
        typer.echo(result)
    except RuntimeError as exc:
        typer.echo(f"FAIL: {exc}", err=True)
        raise typer.Exit(code=1) from exc



@app.command("status")
def status_cmd(
    queue_file: str = typer.Option("", "--queue-file", help="Path to custom queue file"),
) -> None:
    """Show status of queued and sent batch emails."""
    from pathlib import Path
    from imail import batch

    q_path = Path(queue_file).expanduser().resolve() if queue_file else batch.DEFAULT_QUEUE_FILE
    summary = batch.get_queue_summary(q_path)
    typer.echo(f"Queue File: {q_path}")
    typer.echo(f"Total: {summary['total']} | Pending: {summary['pending']} | Sent: {summary['sent']} | Failed: {summary['failed']}")

    items = batch.load_queue(q_path)
    if items:
        typer.echo("\nRecent Queue Items:")
        for it in items[-10:]:
            typer.echo(f"  [{it.get('status', '').upper()}] -> {it.get('to')}: {it.get('subject')} (error: {it.get('error') or 'none'})")


@app.command("batch")
def batch_cmd(
    file: str = typer.Option("", "--file", "-f", help="JSON file containing array of email jobs to queue"),
    run: bool = typer.Option(False, "--run", "-r", help="Dispatch pending queued jobs immediately"),
    limit: int = typer.Option(0, "--limit", "-n", help="Max jobs to process in this run (0 = all)"),
    min_delay: float = typer.Option(1.0, "--min-delay", help="Minimum randomized jitter delay in seconds"),
    max_delay: float = typer.Option(3.0, "--max-delay", help="Maximum randomized jitter delay in seconds"),
    clear: bool = typer.Option(False, "--clear", help="Clear all queue items"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate sends without dispatching"),
    queue_file: str = typer.Option("", "--queue-file", help="Path to custom queue file"),
) -> None:
    """Queue, manage, and dispatch batch emails with randomized intervals."""
    from pathlib import Path
    from imail import batch

    q_path = Path(queue_file).expanduser().resolve() if queue_file else batch.DEFAULT_QUEUE_FILE

    if clear:
        count = batch.clear_queue(q_path)
        typer.echo(f"Cleared {count} items from queue.")
        return

    if file:
        f_path = Path(file).expanduser().resolve()
        if not f_path.is_file():
            typer.echo(f"FAIL: Batch file not found: {file}", err=True)
            raise typer.Exit(code=1)
        try:
            data = json.loads(f_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                typer.echo("FAIL: Batch file must contain a JSON array of objects.", err=True)
                raise typer.Exit(code=1)
            added = batch.enqueue_items(data, q_path)
            typer.echo(f"Enqueued {added} items into {q_path}")
        except Exception as exc:
            typer.echo(f"FAIL: Error parsing batch file: {exc}", err=True)
            raise typer.Exit(code=1)

    if run or (not file and not clear):
        summary = batch.get_queue_summary(q_path)
        if summary["pending"] == 0:
            typer.echo("No pending items in queue to process.")
            return

        typer.echo(f"Starting batch dispatch of {summary['pending']} pending items...")

        def on_progress(item: dict, step: int, total: int) -> None:
            st = item.get("status", "").upper()
            err_str = f" - Error: {item.get('error')}" if item.get("error") else ""
            typer.echo(f"[{step}/{total}] [{st}] {item.get('to')} - {item.get('subject')}{err_str}")

        stats = batch.run_batch_dispatch(
            queue_path=q_path,
            limit=limit if limit > 0 else None,
            min_delay=min_delay,
            max_delay=max_delay,
            dry_run=dry_run,
            progress_callback=on_progress,
        )
        typer.echo(f"Batch completed: {stats['processed']} processed, {stats['sent']} sent, {stats['failed']} failed.")


@app.command("version")
def version_cmd() -> None:
    """Print package version."""
    typer.echo(__version__)


@app.command("mcp")
def mcp_cmd() -> None:
    """Run built-in FastMCP server over stdio."""
    from imail.mcp import run_server
    run_server()


@agent_app.command("schema")
def agent_schema_cmd() -> None:
    """Print JSON command catalog for agents."""
    try:
        typer.echo(agent_mod.schema_json())
    except FileNotFoundError as exc:
        typer.echo(f"FAIL: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@agent_app.command("guide")
def agent_guide_cmd() -> None:
    """Print usage guide for humans and agents."""
    try:
        typer.echo(agent_mod.guide_text())
    except FileNotFoundError as exc:
        typer.echo(f"FAIL: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def main() -> None:
    app()


if __name__ == "__main__":
    main()
