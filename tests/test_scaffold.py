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


def test_validate_fixtures_skips_when_absent(repo_root: Path) -> None:
    from scripts import validate_fixtures

    if (repo_root / "data" / "fixtures" / "fare_observations.parquet").exists():
        pytest.skip("fixture dataset exists — SF-03 owns the validating path")
    assert validate_fixtures.main([]) == 0


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
