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
        False,
        "--markdown",
        "-m",
        help="Format email body as Markdown/HTML",
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
            )
        typer.echo(result)
    except RuntimeError as exc:
        typer.echo(f"FAIL: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("version")
def version_cmd() -> None:
    """Print package version."""
    typer.echo(__version__)


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
