try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    from mcp.server.mcpserver import MCPServer as FastMCP
from imail import mail

mcp = FastMCP("imail")

@mcp.tool()
def doctor() -> str:
    """Verify Mail.app reachability."""
    mail.doctor()
    return "ok: Mail.app reachable"

@mcp.tool()
def list_accounts() -> str:
    """List available Mail.app accounts."""
    return mail.format_accounts()

@mcp.tool()
def list_messages(account: str = "", mailbox: str = "INBOX", limit: int = 20, query: str = "") -> list[dict]:
    """List messages in a mailbox, optionally filtered by query."""
    if query:
        return mail.list_messages(account=account, mailbox=mailbox, limit=limit, query=query)
    return mail.list_messages(account=account, mailbox=mailbox, limit=limit)

@mcp.tool()
def send_message(
    from_addr: str,
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    attachments: list[str] = None
) -> str:
    """Send an email via Mail.app enforcing account walls."""
    return mail.send_message(
        to=to,
        subject=subject,
        body=body,
        from_addr=from_addr,
        cc=cc,
        attachments=attachments
    )

@mcp.tool()
def read_message(account: str = "", index: int = 1, mailbox: str = "INBOX") -> dict:
    """Read complete details of an email by index, including full body, reply-to, and attachments."""
    return mail.read_message(account=account, index=index, mailbox=mailbox)

@mcp.tool()
def reply_message(
    index: int = 1,
    body: str = "",
    account: str = "",
    mailbox: str = "INBOX",
    attachments: list[str] = None,
    from_addr: str = "",
    to: str = "",
    subject: str = "",
    markdown: bool = True,
    zip_attachments: bool = False,
    humanize: bool = False,
    open_draft: bool = False,
) -> str:
    """Reply to an email by index with automatic Reply-To resolution and attachment support."""
    return mail.reply_message(
        account=account,
        index=index,
        mailbox=mailbox,
        body=body,
        attachments=attachments,
        from_addr=from_addr,
        to=to,
        subject=subject,
        markdown=markdown,
        zip_attachments=zip_attachments,
        humanize=humanize,
        open_draft=open_draft,
    )

def run_server():
    mcp.run(transport="stdio")
