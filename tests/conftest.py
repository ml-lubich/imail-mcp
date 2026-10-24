"""Shared test fixtures.

The SQLite fast path in `imail.mail.list_messages` intercepts calls before
they reach `subprocess.run`, so the osascript-based unit tests that mock
`subprocess` must disable it. This conftest disables the fast path for the
entire test session.
"""

from __future__ import annotations

import pytest

from imail import mail


@pytest.fixture(autouse=True)
def _disable_fast_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mail, "_FAST_PATH_ENABLED", False)