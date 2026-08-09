from imail import mcp

def test_mcp_functions():
    assert callable(mcp.doctor)
    assert callable(mcp.list_accounts)
    assert callable(mcp.list_messages)
    assert callable(mcp.send_message)

def test_mcp_run_server(monkeypatch):
    called = False
    def mock_run(*args, **kwargs):
        nonlocal called
        called = True
    monkeypatch.setattr(mcp.mcp, "run", mock_run)
    mcp.run_server()
    assert called
