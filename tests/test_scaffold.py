"""The layout and tooling contract from P0. Everything downstream assumes these hold."""

import datetime as dt
import importlib
import importlib.util
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

# Every directory L0 §1 names, except data/snapshots/ — gitignored and made at runtime.
L0_DIRECTORIES = [
    "specs",
    "config",
    "data",
    "data/fixtures",
    "pipeline",
    "pipeline/adapters",
    "pipeline/schema",
    "pipeline/store",
    "pipeline/quality",
    "pipeline/scheduler",
    "models",
    "models/baseline",
    "models/features",
    "models/backtest",
    "api",
    "web",
    "shared",
    "scripts",
    "tests",
]


def test_python_version_floor() -> None:
    assert sys.version_info >= (3, 12)


def test_l0_directory_tree_exists(repo_root: Path) -> None:
    missing = [d for d in L0_DIRECTORIES if not (repo_root / d).is_dir()]
    assert missing == [], f"L0 §1 requires these directories: {missing}"


def test_snapshots_dir_is_gitignored(repo_root: Path) -> None:
    gitignore = (repo_root / ".gitignore").read_text().splitlines()
    assert "data/snapshots/" in [line.strip() for line in gitignore]

    tracked = subprocess.run(
        ["git", "ls-files", "data/snapshots"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert tracked.stdout.strip() == ""


def test_core_imports() -> None:
    for name in ("pipeline", "models", "api", "shared"):
        assert importlib.import_module(name) is not None


def test_third_party_imports() -> None:
    for name in ("duckdb", "polars", "pyarrow", "pydantic", "fastapi", "yaml"):
        assert importlib.import_module(name) is not None
    # polars is the decision (0001 / P0 stack note); pandas must not creep back in.
    assert importlib.util.find_spec("pandas") is None


def test_validate_fixtures_fails_when_the_input_is_absent(tmp_path: Path) -> None:
    """P0 exited 0 with a skip notice here, when no fixture had been generated yet. SF-03
    generated it, so a missing input is now a failure (review C6) and the old behaviour
    needs --allow-missing, which CI does not pass."""
    from scripts import validate_fixtures

    absent = str(tmp_path / "absent.parquet")

    assert validate_fixtures.main([absent]) == 1
    assert validate_fixtures.main(["--allow-missing", absent]) == 0


def test_pyarrow_pinned_to_one_minor(repo_root: Path) -> None:
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text())
    pins = [d for d in pyproject["project"]["dependencies"] if d.startswith("pyarrow")]
    assert pins == ["pyarrow>=17.0,<18"], "fixture byte-identity depends on one pyarrow minor"


def test_clock_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from shared import clock

    monkeypatch.setenv("SNAP_TODAY", "2026-09-09")
    assert clock.today_utc() == dt.date(2026, 9, 9)
    assert clock.now_utc() == dt.datetime(2026, 9, 9, tzinfo=dt.UTC)

    monkeypatch.delenv("SNAP_TODAY", raising=False)
    assert clock.today_utc() == dt.datetime.now(dt.UTC).date()
    assert clock.now_utc().tzinfo is dt.UTC

    monkeypatch.setenv("SNAP_TODAY", "not-a-date")
    with pytest.raises(ValueError):
        clock.today_utc()
    with pytest.raises(ValueError):
        clock.now_utc()


@pytest.mark.parametrize(
    "pin",
    ["2026-09-09T12:34:56", "2026-09-09T12:34:56+00:00", "2026-09-09 12:34:56", "20260909"],
)
def test_a_datetime_shaped_clock_pin_fails_in_both_functions(
    monkeypatch: pytest.MonkeyPatch, pin: str
) -> None:
    """One parser, one answer. today_utc() used to raise on these while now_utc() happily
    returned 12:34:56 UTC — a pin that half-worked is worse than one that fails."""
    from shared import clock

    monkeypatch.setenv("SNAP_TODAY", pin)

    with pytest.raises(ValueError):
        clock.today_utc()
    with pytest.raises(ValueError):
        clock.now_utc()


def test_pinned_now_is_midnight_of_pinned_today(monkeypatch: pytest.MonkeyPatch) -> None:
    from shared import clock

    monkeypatch.setenv("SNAP_TODAY", "2026-09-09")

    assert clock.now_utc().date() == clock.today_utc()
    assert clock.now_utc().timetz() == dt.time(0, 0, tzinfo=dt.UTC)


def test_a_blank_clock_pin_falls_back_to_the_real_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    from shared import clock

    monkeypatch.setenv("SNAP_TODAY", "   ")

    assert clock.today_utc() == dt.datetime.now(dt.UTC).date()
    assert clock.now_utc().tzinfo is dt.UTC


# C5 — discovery reaches unit tests beside code, and the suite runs offline.


PROBE_SOURCE = '''
"""Temporary probe written by tests/test_scaffold.py. Deleted in the same test."""

import socket

import pytest


def test_probe_is_collected() -> None:
    assert True


def test_probe_is_covered_by_the_offline_guard() -> None:
    with pytest.raises(RuntimeError, match="blocked"):
        socket.socket().connect(("93.184.216.34", 80))


def test_probe_is_covered_by_the_fixture_env_isolation() -> None:
    import os

    assert "SNAP_USE_FIXTURES" not in os.environ
'''


def test_adjacent_unit_tests_are_collected(repo_root: Path) -> None:
    """L0 §1 puts unit tests beside the code they test, but testpaths=["tests"] never
    reached them: a future adapter's unit tests would have been silently uncollected by
    the standard command (review C5). Written, collected, run, removed."""
    probe = repo_root / "pipeline" / "schema" / "test_discovery_probe.py"
    probe.write_text(PROBE_SOURCE)
    try:
        collected = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        # -q reports one line per collected file: "<path>: <count>".
        assert "pipeline/schema/test_discovery_probe.py: 3" in collected.stdout

        run = subprocess.run(
            [sys.executable, "-m", "pytest", str(probe), "-v", "--no-header"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stdout + run.stderr
        assert "3 passed" in run.stdout, run.stdout
    finally:
        probe.unlink()
        for cached in (repo_root / "pipeline" / "schema" / "__pycache__").glob(
            "test_discovery_probe*"
        ):
            cached.unlink()


def test_the_suite_cannot_open_an_outbound_socket() -> None:
    """The no-network rule was prose. CI does not deny egress, and this project does not
    get to assume a GitHub runner has none (review C5)."""
    import socket

    with pytest.raises(RuntimeError, match="blocked"):
        socket.socket().connect(("93.184.216.34", 80))

    with pytest.raises(RuntimeError, match="blocked"):
        socket.create_connection(("example.com", 443), timeout=0.1)


def test_the_offline_guard_still_allows_loopback() -> None:
    """DuckDB, pyarrow and a FastAPI TestClient may open a local socket; the guard is
    narrow enough to let SF-07's tests work."""
    import socket

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        client = socket.socket()
        client.connect(listener.getsockname())
        client.close()
    finally:
        listener.close()
