from __future__ import annotations

from pathlib import Path

import pytest

from imail import mail


@pytest.fixture(autouse=True)
def _use_sanitized_accounts_config(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep tests independent from the developer's ignored accounts.json."""
    monkeypatch.setattr(mail, "_FAST_PATH_ENABLED", False)
    if request.node.get_closest_marker("accounts_path"):
        return
    fixture_path = Path(__file__).parent / "fixtures" / "accounts.json"
    monkeypatch.setattr(mail, "accounts_json_path", lambda: fixture_path)
