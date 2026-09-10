# Review evidence and limits

Reviewed the workspace at `b26c374` on 2026-09-09. No pasted bundle arrived; the workspace contained the described specs, implementation and git history, plus the binary fixture. The working tree was clean before this review. Production code and existing tests were not changed.

## Checks run

| Check | Result |
|---|---|
| `.venv/bin/python -m pytest` | **142 passed, 1 skipped**, 33.55 seconds |
| `.venv/bin/ruff check .` | Passed |
| `.venv/bin/ruff format --check .` | Passed; 36 files already formatted |
| Fixture validity and regeneration | Passed as part of pytest, including every-row validation, subprocess CLI validation, byte-identical regeneration and checksum comparison |
| Target Oracle ARM Linux execution | Not run |
| Live Travelpayouts / fast-flights collection | Not run; credentials, selected versions and source evidence were not supplied |
| Remote GitHub branch protection / historical CI status | Not inspected; local workflow and git history only |

The skipped test is the P0-only missing-fixture case; it skips because the real fixture now exists. The commands used the existing virtual environment, not a newly resolved dependency installation.

Observed runtime versions: Python **3.12.14**, DuckDB **1.5.5**, PyArrow **17.0.0**, Polars **1.44.2**, Pydantic **2.13.5**.

## Additional adversarial probes

All writes used temporary directories. The concurrency probe controlled interleaving with a barrier; the partial-publication probe placed a Parquet header at the final path before invoking the reader. These reproduce reachable timing windows; they are not sustained-load benchmarks.

| Probe | Observed result | Finding |
|---|---|---|
| Write 06:00 `ok`, then 18:00 `rejected`, same daily key | Default read returns old `ok` row | T2 |
| Health as of Sep 1 with only Sep 9 data | Reports Sep 9 source as recent | C4 |
| Read `route_key=[]` or `source=[]` | DuckDB `ParserException`, `IN ()` | C3 |
| Read `limit=-1` | DuckDB `BinderException` | C3 |
| Construct a naive timestamp filter | Accepted | C3 |
| Canonical amount `True` | Coerced to 1, validator reports no violations | C2 |
| Canonical amount `2**63` | Validator reports no violations; writer raises `OverflowError` | C2 |
| Canonical source-price age -2 | Validator reports no violations | C2 |
| Canonical currency `ZZZ` | Validator reports no violations | S2 |
| Run ID `x/../../../../../escaped` | Writes `data/snapshots/escaped.parquet` outside the fare store root | C2 |
| `model_copy(update={"amount_minor": -1})` | Validator reports no violations; frame read returns -1; record read raises | C1 |
| `build_observation(carrier_primary=" BA ", ...)` | Carrier becomes `BA`, ID no longer recomputes | S5 |
| One batch `[18:00/$100, 06:00/$200]` | Retains $200 | T3 |
| Two writes with identical run/time/key and differing amounts | Read retains the first amount in this execution | T3 |
| DuckDB Hive-enabled read of a written part | Reads source/route/fetched-date successfully | T4 |
| Reader invoked while final part is incomplete | `InvalidInputException`, file too small to be Parquet | T1 |
| Two writers paused after selecting the same free part name | Both write results report the same target path | T1 |
| `SNAP_TODAY=2026-09-09T12:34:56` | `today_utc()` raises; `now_utc()` returns 12:34:56 UTC | C4 |

## Minimal reproduction of the central store/validation failures

Run from the repository root with the current development environment. Helpers are existing test utilities; the example makes no production-store changes.

```python
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from pipeline.schema import DataQuality, validate
from pipeline.store import ReadFilters
from tests.store import make_observation, store_at

with TemporaryDirectory() as directory:
    root = Path(directory)
    store = store_at(root / "quality")
    early = make_observation()
    late = make_observation(
        fetched_at=datetime(2026, 9, 9, 18, tzinfo=UTC),
        data_quality=DataQuality.REJECTED,
    )
    store.write([early])
    store.write([late])
    print(store.read()[0].data_quality)  # ok: older version resurfaces

    try:
        store.read(ReadFilters(route_key=[]))
    except Exception as exc:
        print(type(exc).__name__)  # ParserException

    invalid = early.model_copy(update={"amount_minor": -1})
    print(validate(invalid))  # []
    invalid_store = store_at(root / "invalid")
    invalid_store.write([invalid])
    print(invalid_store.read_frame()["amount_minor"].to_list())  # [-1]
    try:
        invalid_store.read()
    except Exception as exc:
        print(type(exc).__name__)  # ValidationError
```

## Evidence boundaries

No deployed service, adapter, model or API exists in this checkout beyond the scaffold. Prediction findings are counterexamples to the specifications, not measured model-performance claims. The existing tests passing does not resolve those counterexamples. File-count estimates in T4 are arithmetic scenarios, not measured production growth or a claim that Parquet cannot handle this project's modest row volume.

Primary-source checks were limited to the [Travelpayouts API reference](https://travelpayouts.github.io/slate/), [fast-flights upstream repository](https://github.com/AWeirdDev/flights), and [Oracle Always Free documentation](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm). Provider-specific claims are linked where used in the findings. No conclusion about source access, account entitlement or sustained scraper availability is inferred from those pages alone.
