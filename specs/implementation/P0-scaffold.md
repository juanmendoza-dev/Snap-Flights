# P0 — Project Scaffold

**Tier:** L3 (build spec) · **Parent:** no L2 spec — this exists only to make L0 §1 real.
**Execution slot:** first. Nothing else in `specs/implementation/` can start until this is on `main`.

## Summary

Turn the empty repo into a runnable Python 3.12 project: one `uv` environment spanning
`pipeline/ models/ api/ shared/`, the directory tree from L0 §1, lint + test config, and a
CI workflow that runs the test suite and validates every fixture row against the schema.

No product code. No schema, no store, no model, no API — those are SF-03/06/07.

## Depends on

- L0 §1 (repo layout is binding).
- Decision 0001 (Python 3.12+, `uv`, FastAPI, Pydantic v2, Parquet + DuckDB).

## Stack note — dataframe library

**polars**, not pandas, for every stats/frame path in this project. One line of justification:
polars is Arrow-native so a DuckDB result crosses into a frame zero-copy (`rel.arrow()` →
`pl.from_arrow`), it has no index semantics to leak into the frozen `read_frame()` column
contract (SF-03-build §7), and its dtypes are strict enough that the contract is assertable
in a test. pandas is not a dependency of this project.

## Files owned

```
pyproject.toml                       # project metadata, deps, ruff + pytest config
uv.lock                              # committed lockfile — CI installs with --locked
.python-version                      # "3.12"
.gitignore                           # extended: .venv/, .pytest_cache/, .ruff_cache/, reports
.github/workflows/ci.yml             # lint + tests + fixture validation, no network in tests
scripts/validate_fixtures.py         # fixture-vs-schema validator (skeleton here, body in SF-03)
scripts/__init__.py                  # makes scripts/ importable by tests
pipeline/__init__.py                 # namespace only
pipeline/README.md                   # what lives under pipeline/, per L0 §1
models/__init__.py                   # namespace only
models/README.md                     # what lives under models/, per L0 §1
api/__init__.py                      # namespace only
shared/__init__.py                   # namespace only
config/.gitkeep                      # config/ exists before SF-06 writes baseline.yaml
data/fixtures/.gitkeep               # replaced by real fixtures in SF-03
web/.gitkeep                         # deferred (D3) — directory exists, stays empty
tests/__init__.py                    # namespace only
tests/conftest.py                    # repo-root path fixture + SNAP_USE_FIXTURES isolation
tests/test_scaffold.py               # asserts the layout + tooling contract
```

**Directories created empty with `.gitkeep`** (owned by later specs, created here so L0 §1
is satisfied on day one): `pipeline/adapters/`, `pipeline/schema/`, `pipeline/store/`,
`pipeline/quality/`, `pipeline/scheduler/`, `models/baseline/`, `models/features/`,
`models/backtest/`, `data/snapshots/` is **not** created (gitignored, made at runtime).

**Shared-ownership note:** `scripts/validate_fixtures.py` is created here as a skeleton and
its body is written in SF-03. This is the one file two build specs touch; it is called out
so the second edit is not read as a conflict.

## `pyproject.toml` — committed content

```toml
[project]
name = "snap-flights"
version = "0.1.0"
description = "Flight search with price prediction as the headline feature."
requires-python = ">=3.12"
dependencies = [
    "duckdb>=1.1,<2",
    "fastapi>=0.115,<1",
    "polars>=1.9,<2",
    "pyarrow>=17.0,<18",
    "pydantic>=2.9,<3",
    "pyyaml>=6.0,<7",
    "uvicorn[standard]>=0.31,<1",
]

[dependency-groups]
dev = [
    "httpx>=0.27,<1",
    "pytest>=8.3,<9",
    "ruff>=0.6,<1",
]

[tool.uv]
package = false

[tool.ruff]
line-length = 100
target-version = "py312"
extend-exclude = ["data"]

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM", "RUF"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
addopts = "-q --strict-markers"
markers = [
    "slow: takes more than a second (fixture regeneration, backtest)",
]
```

`pyarrow` is pinned to a single minor (`>=17.0,<18`) on purpose: the fixture Parquet file is
byte-identity-tested (SF-03-build §5) and the writer version is embedded in the file's
`created_by` metadata. A pyarrow minor bump is a deliberate regenerate-and-review change,
exactly as L0 §7 requires.

`[tool.uv] package = false` + `pythonpath = ["."]` keeps the flat top-level layout L0 §1
mandates (`pipeline/`, `models/`, `api/` at the repo root) instead of `uv init`'s default
`src/` layout. Do not run bare `uv init`; write `pyproject.toml` as above, then `uv sync`.

## `.gitignore` — lines added to the existing file

```
.pytest_cache/
.ruff_cache/
.coverage
models/backtest/reports/*.json
!models/backtest/reports/latest.json
```

`data/snapshots/`, `.venv/`, `__pycache__/`, `*.pyc`, `.DS_Store` are already there — do not
duplicate them.

## `.github/workflows/ci.yml` — committed content

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  check:
    runs-on: ubuntu-latest
    env:
      SNAP_USE_FIXTURES: "1"
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
      - run: uv python install 3.12
      - run: uv sync --locked --dev
      - name: Lint
        run: uv run ruff check .
      - name: Format check
        run: uv run ruff format --check .
      - name: Tests
        run: uv run pytest
      - name: Validate fixtures against the schema
        run: uv run python scripts/validate_fixtures.py
```

**Network rule:** dependency installation uses the network (unavoidable). Everything after
`uv sync` must run with no outbound calls. No test may reach a network; adapters are not in
this pass, so nothing legitimately needs one.

## Public signatures created here

```python
# scripts/validate_fixtures.py

def main(argv: list[str] | None = None) -> int:
    """Validate every row of data/fixtures/fare_observations.parquet against the
    canonical schema. Returns 0 on success, 1 on any violation, 0 with a printed
    skip notice when the fixture file does not exist yet (P0 state)."""
```

```python
# tests/conftest.py
import pytest
from pathlib import Path

@pytest.fixture(scope="session")
def repo_root() -> Path: ...

@pytest.fixture(autouse=True)
def _clean_fixture_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delete SNAP_USE_FIXTURES from the environment before every test so a test
    that wants fixture mode must opt in explicitly. Prevents CI's job-level
    SNAP_USE_FIXTURES=1 from silently changing unit-test behaviour."""
```

## Config file schemas

None. P0 creates `config/` empty. `config/baseline.yaml` is SF-06's, `config/api.yaml` is
SF-07's, `config/quality.yaml` is SF-05's and is **not** created in this pass.

## Test list

`tests/test_scaffold.py`:

| Test | Asserts |
|------|---------|
| `test_python_version_floor` | `sys.version_info >= (3, 12)` |
| `test_l0_directory_tree_exists` | every directory named in L0 §1 exists, except `data/snapshots/` |
| `test_snapshots_dir_is_gitignored` | `data/snapshots/` appears in `.gitignore` and is not tracked by git |
| `test_core_imports` | `import pipeline, models, api, shared` all succeed |
| `test_third_party_imports` | `duckdb`, `polars`, `pyarrow`, `pydantic`, `fastapi`, `yaml` import; `pandas` does **not** (asserts the polars decision is not quietly violated) |
| `test_validate_fixtures_skips_when_absent` | `scripts.validate_fixtures.main([])` returns `0` when the fixture file is missing |
| `test_pyarrow_pinned_to_one_minor` | `pyproject.toml` constrains `pyarrow` to a single minor version (guards fixture byte-identity) |

There is no parent L2 spec, so there is no Done-when mapping table. The Done-when list below
stands in.

## Done when

- `uv sync --locked --dev` succeeds from a clean checkout on Python 3.12.
- `uv run ruff check . && uv run ruff format --check .` is clean.
- `uv run pytest` passes with the seven tests above.
- `uv run python scripts/validate_fixtures.py` exits 0 and prints a skip notice.
- The CI workflow is green on `main`.
- Every directory in L0 §1 exists in the tree (`data/snapshots/` excepted).

## Out of scope

- Any schema, store, model, or API code.
- `config/routes.yaml` (SF-04, skipped this pass), `config/quality.yaml` (SF-05, skipped).
- Deployment, Dockerfile, Oracle Cloud provisioning (ops, after the phase ends).
- Pre-commit hooks, coverage gates, type checking. Ruff + pytest is the whole quality bar
  for this phase.

## Ordered commit plan

| # | Message | Contains |
|---|---------|----------|
| 1 | `Set up the uv project and pin the toolchain` | `pyproject.toml`, `.python-version`, `uv.lock`, `.gitignore` additions |
| 2 | `Lay out the directory tree from L0` | all `__init__.py`, `.gitkeep`, `pipeline/README.md`, `models/README.md` |
| 3 | `Add the scaffold tests and pytest conftest` | `tests/__init__.py`, `tests/conftest.py`, `tests/test_scaffold.py` |
| 4 | `Add the fixture validator skeleton` | `scripts/__init__.py`, `scripts/validate_fixtures.py` |
| 5 | `Run lint, tests and fixture validation in CI` | `.github/workflows/ci.yml` |

Push after each. Commit 5 last so the first green CI run covers the finished scaffold.

## Interfaces frozen for downstream

SF-03 (and everything after) may assume, without re-checking:

1. Imports are rooted at the repo root: `from pipeline.schema import ...`,
   `from models.baseline import ...`, `from shared.settings import ...`. No `src/` prefix.
2. The runtime is Python 3.12+, dependencies resolve from the committed `uv.lock`, and
   `duckdb`, `polars`, `pyarrow`, `pydantic` v2, `fastapi`, `yaml` are importable.
3. `pandas` is **not** available and must not be added.
4. `config/` exists and is empty; a spec that needs a config file creates it.
5. `scripts/validate_fixtures.py` exists with `main(argv) -> int` and is already wired into
   CI. SF-03 fills its body; it does not touch `.github/workflows/ci.yml`.
6. `tests/conftest.py` provides `repo_root` and unsets `SNAP_USE_FIXTURES` before every
   test. A test that needs fixture mode sets it itself.
7. Line length is 100 and the ruff rule set is fixed. Code that fails `ruff check` fails CI.
