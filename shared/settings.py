"""The single reader of ``SNAP_USE_FIXTURES`` and the data roots (SF-03-build §2.6).

``pipeline/``, ``models/`` and ``api/`` all ask this module which mode they are in, so they
cannot disagree. Nothing else reads the environment variable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

USE_FIXTURES_ENV: str = "SNAP_USE_FIXTURES"
TRUTHY: frozenset[str] = frozenset({"1", "true", "yes"})

_DEFAULT_REPO_ROOT: Path = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class DataSettings:
    repo_root: Path
    snapshots_root: Path
    fixtures_root: Path
    use_fixtures: bool

    @property
    def fixture_parquet(self) -> Path:
        return self.fixtures_root / "fare_observations.parquet"

    @property
    def routes_csv(self) -> Path:
        return self.fixtures_root / "routes.csv"


def _env_use_fixtures() -> bool:
    return os.environ.get(USE_FIXTURES_ENV, "").strip().lower() in TRUTHY


def load_data_settings(
    *, repo_root: Path | None = None, use_fixtures: bool | None = None
) -> DataSettings:
    """Explicit arguments win over the environment; the environment wins over defaults.
    repo_root defaults to the package root two levels above this file."""
    root = Path(repo_root).resolve() if repo_root is not None else _DEFAULT_REPO_ROOT
    return DataSettings(
        repo_root=root,
        snapshots_root=root / "data" / "snapshots" / "fare_observations",
        fixtures_root=root / "data" / "fixtures",
        use_fixtures=_env_use_fixtures() if use_fixtures is None else use_fixtures,
    )


def use_fixtures() -> bool:
    """The **process** fixture mode, straight from the environment.

    A component that was handed explicit settings must report `settings.use_fixtures`
    instead: `load_data_settings(use_fixtures=...)` deliberately lets an injected store
    disagree with the environment, and reading the variable behind its back labels an
    injected live store "fixture mode" and vice versa (review C4). Use this only where
    there is no settings object to ask — a process-level default.
    """
    return _env_use_fixtures()


@lru_cache(maxsize=1)
def _cached_default_settings(root: Path, fixtures: bool) -> DataSettings:
    return load_data_settings(repo_root=root, use_fixtures=fixtures)


def default_data_settings() -> DataSettings:
    """Process-wide settings, cached per (repo root, fixture mode) so a test that flips
    the environment variable still gets fresh settings."""
    return _cached_default_settings(_DEFAULT_REPO_ROOT, _env_use_fixtures())
