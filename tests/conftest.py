from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """The repository root, resolved from this file rather than the working directory."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean_fixture_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delete SNAP_USE_FIXTURES from the environment before every test so a test
    that wants fixture mode must opt in explicitly. Prevents CI's job-level
    SNAP_USE_FIXTURES=1 from silently changing unit-test behaviour."""
    monkeypatch.delenv("SNAP_USE_FIXTURES", raising=False)
