# Implemented code and CI

All observations below concern code at `b26c374`, unless explicitly described as a future integration gap. The existing suite passed; see [verification](08-verification.md).

### C1 — Validation trusts model instances that can bypass validation
- **Severity:** high
- **Where:** `pipeline/schema/validation.py:validate`; `record.py:FareObservation`; `SnapshotStore.write/read_frame/read`; `arrow.py:table_to_records`.
- **What's wrong:** For a `FareObservation`, `validate()` checks only ID and schema version. Pydantic `model_copy(update=...)` can carry unvalidated values. A frozen model also has a mutable `quality_flags` list. The store never calls the batch validator before writing. Reproduced: copying a valid record with `amount_minor=-1` yields `validate(record)==[]`; the writer persists it; `read_frame()` returns -1 while `read()` raises `ValidationError`. Even direct ordinary construction permits a wrong but well-shaped observation ID until the separate validator is invoked.
- **Why it matters:** SF-05 is likely to use `model_copy` to stamp quality on a frozen record. An accidental invalid update or wrong ID can poison history while the supposedly shared list/frame read contract diverges. A malformed key can dedup unrelated rows before any downstream check.
- **Recommended fix:** Fully revalidate model instances from their dumped field values at trust boundaries; do not rely on their class identity. Make write validation mandatory before grouping/dedup/publication, returning a structured failure for invalid batches. Use a validated helper for quality updates and an immutable flag tuple internally if immutability is promised. Validate logical IDs/schema version on canonical read reconstruction too. Add the negative-price copy test, wrong-ID write test and invalid flag mutation test, with both read paths required to agree on valid data and reject invalid data consistently.
- **Confidence:** high — the invalid write and list/frame divergence were reproduced.

### C2 — Int64 and UUID contracts are not enforced before persistence
- **Severity:** high
- **Where:** L0 §3; `record.py` numeric fields/`ingest_run_id`; `paths.py:part_path`; Arrow schema.
- **What's wrong:** Python integers have no int64 upper bound, and coercive Pydantic fields accept booleans/integral floats. `amount_minor=True` validates as 1; `amount_minor=2**63` validates but raises `OverflowError` during Arrow conversion. `observed_price_age_seconds=-2` also validates. `ingest_run_id` is an unrestricted string used in a filesystem path: `x/../../../../../escaped` validates and writes `data/snapshots/escaped.parquet` outside the fare store's scan tree.
- **Why it matters:** A malformed record can fail after earlier partition groups have already been published. A malformed run ID writes outside its partition and can escape the store root under the process's permissions. This is currently an internal producer boundary, not a demonstrated remotely exploitable API.
- **Recommended fix:** Use strict bounded integers for all int64-backed fields, with `0 <= age <= 2**63-1`, positive price/passengers, and appropriate stop/version bounds. Parse/canonicalize run IDs as UUIDs and use their canonical string for paths. Reject separators/dot segments in path components and assert resolved targets remain under the store root. Prevalidate/convert the whole batch before any publication. Add boolean, integral-float, overflow, negative-age and traversal cases. Keep semantic date impossibility in the gate/quarantine design if that is the selected boundary.
- **Confidence:** high — amount overflow, boolean coercion, negative age and an escaped write were reproduced in temporary directories.

### C3 — Accepted read filters generate invalid SQL or ambiguous time semantics
- **Severity:** medium
- **Where:** `pipeline/store/filters.py:ReadFilters/as_list`; `_build_query`.
- **What's wrong:** An empty sequence becomes `IN ()`, which DuckDB rejects. Negative limits are accepted by Pydantic and rejected by DuckDB. Naive `fetched_at` filters are accepted despite the build spec's timezone-aware UTC contract. Reversed ranges and arbitrary route strings are not validated. On an empty store these inputs can return an empty result without reaching SQL, making behavior depend on whether data exists.
- **Why it matters:** A valid scheduler/model request for an empty route selection produces a database exception instead of an empty frame. A caller's local naive cutoff is silently interpreted under a UTC session. API callers can see different failure modes after the first data file lands.
- **Recommended fix:** Define empty-list filters as an empty result with the frozen schema; short-circuit before building SQL. Require `limit >= 0` and strict integers. Reject naive/non-UTC timestamps or explicitly normalize aware offsets, matching the chosen record/filter contract. Validate range ordering and route format at construction. Add each case against both an empty and populated store, preserving the existing explicit quality-filter precedence once T2 is fixed.
- **Confidence:** high — empty-list SQL errors, negative-limit errors and naive timestamp acceptance were reproduced.

### C4 — Health and the clock can disagree with the requested as-of date
- **Severity:** medium
- **Where:** `SnapshotStore.sources_with_recent_data`; `shared/clock.py`; `shared/settings.py:use_fixtures`; SF-07-build health handler.
- **What's wrong:** Health applies only a lower date bound; asking as of September 1 returns a September 9 observation as recent. It also has the quality-resolution defect in T2. `today_utc()` parses a date, while `now_utc()` parses a datetime and replaces its timezone. With `SNAP_TODAY=2026-09-09T12:34:56`, the former raises and the latter succeeds despite the promised identical date-only behavior. The future health handler reads fixture mode from the environment even when its injected store settings explicitly override that environment.
- **Why it matters:** Historical/deterministic health checks can count future data, a typo creates inconsistent clock behavior, and an injected live store can be labeled fixture mode or vice versa. In fixture mode with a historical as-of date, the future-data bug is immediately reachable.
- **Recommended fix:** Resolve and validate the date override in one private date parser; derive pinned `now_utc()` as midnight from it. Health must bound fetched dates by `[as_of-within_days, as_of]`, with a documented inclusive convention and nonnegative window, over the same resolved rows as ordinary reads. Derive the mode from `store.settings`. Add a future-only source, invalid datetime-shaped date pin, and settings/environment disagreement tests.
- **Confidence:** high — future-source inclusion and clock parser disagreement were reproduced; the injected-settings issue is a specified future handler defect.

### C5 — CI verifies the dense development path, not the promised runtime boundary
- **Severity:** medium
- **Where:** `.github/workflows/ci.yml`; `pyproject.toml`; `tests/test_scaffold.py`; SF-07-build no-network test fallback.
- **What's wrong:** CI installs all dev dependencies on one Ubuntu runner; it has no production-only import/startup check or target ARM Linux check. `httpx` being dev-only is hidden until SF-01 is deployed. The no-network rule is prose: the workflow does not deny egress, and SF-07 suggests relying on CI no-egress if a socket test is dropped. `testpaths=["tests"]` also conflicts with L0's instruction that unit tests live beside code: future adjacent unit tests will not be discovered by the standard command. The fixture suite does not exercise storage concurrency or the counterexamples in this review.
- **Why it matters:** Green CI can miss undeclared runtime dependencies, silently uncollected adapter unit tests, and accidental external calls. Fixture byte identity is proven locally but not by this review on the eventual ARM Linux deployment environment.
- **Recommended fix:** Standardize all tests under `tests/` or expand discovery and verify adjacent-test collection explicitly. Add offline transport/socket blocking for tests, with narrowly scoped local exceptions if actually needed; do not assert GitHub-hosted runners have no egress. Once adapters land, build a separate `uv sync --locked --no-dev` environment and smoke-import/run production entry points. Add an ARM Linux smoke job if available within the project's runner allowance, or a documented deployment check on the actual VM. Add regression tests for the concrete store/schema bugs; coverage percentages and an elaborate test framework are not prerequisites.
- **Confidence:** high on current workflow gaps; actual ARM compatibility and remote CI result history were not established.

### C6 — Fixture validation still treats a missing file as success
- **Severity:** low
- **Where:** `scripts/validate_fixtures.py:main`; `tests/fixtures/test_fixture_dataset.py::test_validate_fixtures_script_skips_a_missing_file`; P0 temporary scaffold contract.
- **What's wrong:** Even after SF-03, the validator returns exit 0 for a nonexistent explicitly supplied path. A typo or missing deployment fixture is reported as a successful skip. The full current test suite separately requires the committed Parquet, so this is not a claim that deleting the fixture makes all CI green.
- **Why it matters:** Running the validator as a standalone operational check can falsely succeed while validating nothing.
- **Recommended fix:** Make missing required input a nonzero exit now that fixtures are implemented. If a scaffold compatibility mode is retained, require an explicit `--allow-missing` flag that CI and production checks do not use. Test a typo path as a failure and update the completed P0-era skip expectation.
- **Confidence:** high — explicit current control flow and test expectation.
