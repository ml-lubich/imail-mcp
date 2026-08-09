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
def list_messages(account: str = "", mailbox: str = "INBOX", limit: int = 20) -> list[dict]:
    """List messages in a mailbox."""
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

def run_server():
    mcp.run(transport="stdio")
