"""Row and batch validation for the canonical schema (SF-03 'What to build' §1).

``validate()`` accepts either a built :class:`FareObservation` or a raw dict straight off
Parquet, and returns a list of :class:`Violation` — empty means valid. Most field-level
rules live on the Pydantic model; this module maps a pydantic error back to a stable
``ViolationCode`` so a batch report can count violations by kind rather than by prose.

Two rules cannot live on the model and are checked here: the ``observation_id`` must
recompute from the record's own natural key (L0 §2), and ``schema_version`` must be the
version this code speaks.

A :class:`FareObservation` instance is **not** trusted for being one. ``model_copy(update=)``
and ``model_construct()`` both produce instances that never met a validator, so every entry
point here revalidates from the record's own dumped field values (review C1). Class identity
is not evidence.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from pipeline.schema.identity import observation_id_for
from pipeline.schema.record import SCHEMA_VERSION, FareObservation

SAMPLE_LIMIT: int = 20


class ViolationCode(StrEnum):
    MISSING_REQUIRED = "missing_required"
    WRONG_TYPE = "wrong_type"
    BAD_ENUM = "bad_enum"
    BAD_IATA = "bad_iata"
    BAD_CURRENCY = "bad_currency"
    BAD_ROUTE_KEY = "bad_route_key"
    NAIVE_TIMESTAMP = "naive_timestamp"
    NON_UTC_TIMESTAMP = "non_utc_timestamp"
    NONPOSITIVE_AMOUNT = "nonpositive_amount"
    RETURN_DATE_MISMATCH = "return_date_mismatch"
    OBSERVATION_ID_MISMATCH = "observation_id_mismatch"
    BAD_SCHEMA_VERSION = "bad_schema_version"
    OUT_OF_RANGE = "out_of_range"
    BAD_INGEST_RUN_ID = "bad_ingest_run_id"


class InvalidBatchError(ValueError):
    """A batch crossing a trust boundary contained invalid rows.

    Carries the full :class:`BatchReport` so a caller can quarantine by violation code
    rather than by parsing prose. A ``ValueError`` so existing broad handlers still catch it.
    """

    def __init__(self, report: BatchReport) -> None:
        super().__init__(f"batch contains invalid rows:\n{report}")
        self.report = report


@dataclass(frozen=True, slots=True)
class Violation:
    code: ViolationCode
    field: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class BatchReport:
    total: int
    valid: int
    invalid: int
    counts_by_code: dict[ViolationCode, int] = field(default_factory=dict)
    sample: list[tuple[int, Violation]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.invalid == 0

    def __str__(self) -> str:
        head = f"{self.total} rows: {self.valid} valid, {self.invalid} invalid"
        if not self.counts_by_code:
            return head
        counts = ", ".join(
            f"{code.value}={count}" for code, count in sorted(self.counts_by_code.items())
        )
        lines = [head, f"  violations by code: {counts}"]
        lines.extend(
            f"  row {index}: {violation.code.value} [{violation.field or '-'}] {violation.detail}"
            for index, violation in self.sample
        )
        return "\n".join(lines)


# Pattern / length failures carry no code of their own; the field says which rule broke.
_FIELD_CODES: dict[str, ViolationCode] = {
    "origin": ViolationCode.BAD_IATA,
    "destination": ViolationCode.BAD_IATA,
    "currency": ViolationCode.BAD_CURRENCY,
    "route_key": ViolationCode.BAD_ROUTE_KEY,
    "amount_minor": ViolationCode.NONPOSITIVE_AMOUNT,
}

# A model validator raises ValueError prefixed with its code; these are the codes it can use.
_MODEL_CODES: tuple[ViolationCode, ...] = (
    ViolationCode.NAIVE_TIMESTAMP,
    ViolationCode.NON_UTC_TIMESTAMP,
    ViolationCode.BAD_ROUTE_KEY,
    ViolationCode.RETURN_DATE_MISMATCH,
    ViolationCode.BAD_INGEST_RUN_ID,
)

_MODEL_CODE_FIELDS: dict[ViolationCode, str] = {
    ViolationCode.NAIVE_TIMESTAMP: "fetched_at",
    ViolationCode.NON_UTC_TIMESTAMP: "fetched_at",
    ViolationCode.BAD_ROUTE_KEY: "route_key",
    ViolationCode.RETURN_DATE_MISMATCH: "return_date",
    ViolationCode.BAD_INGEST_RUN_ID: "ingest_run_id",
}

_STRING_SHAPE_ERRORS: frozenset[str] = frozenset(
    {"string_pattern_mismatch", "string_too_short", "string_too_long"}
)

_BOUND_ERRORS: frozenset[str] = frozenset(
    {"greater_than", "greater_than_equal", "less_than", "less_than_equal"}
)

# An int64 field that is too large is out of range, not "nonpositive": amount_minor is the
# one field whose lower bound has a code of its own, so only its lower-bound error keeps it.
_LOWER_BOUND_ERRORS: frozenset[str] = frozenset({"greater_than", "greater_than_equal"})


def _violation_from_error(error: dict[str, Any]) -> Violation:
    location = error.get("loc") or ()
    name = str(location[0]) if location else None
    error_type = str(error.get("type", ""))
    message = str(error.get("msg", ""))

    if error_type == "value_error":
        for code in _MODEL_CODES:
            if code.value in message:
                return Violation(code, name or _MODEL_CODE_FIELDS[code], message)
        return Violation(ViolationCode.WRONG_TYPE, name, message)

    if error_type == "missing":
        return Violation(ViolationCode.MISSING_REQUIRED, name, message)

    if error_type == "enum":
        return Violation(ViolationCode.BAD_ENUM, name, message)

    if error_type in _BOUND_ERRORS:
        code = _FIELD_CODES.get(name or "", ViolationCode.OUT_OF_RANGE)
        if code is ViolationCode.NONPOSITIVE_AMOUNT and error_type not in _LOWER_BOUND_ERRORS:
            code = ViolationCode.OUT_OF_RANGE
        return Violation(code, name, message)

    if error_type in _STRING_SHAPE_ERRORS:
        code = _FIELD_CODES.get(name or "", ViolationCode.WRONG_TYPE)
        return Violation(code, name, message)

    return Violation(ViolationCode.WRONG_TYPE, name, message)


def logical_violations(record: FareObservation) -> list[Violation]:
    """The two rules that cannot live on the model: the id recomputes from the record's own
    natural key (L0 §2), and the schema version is the one this code speaks."""
    violations: list[Violation] = []

    expected_id = observation_id_for(record)
    if record.observation_id != expected_id:
        violations.append(
            Violation(
                ViolationCode.OBSERVATION_ID_MISMATCH,
                "observation_id",
                f"observation_id {record.observation_id!r} does not recompute from the "
                f"natural key (expected {expected_id!r})",
            )
        )

    if record.schema_version != SCHEMA_VERSION:
        violations.append(
            Violation(
                ViolationCode.BAD_SCHEMA_VERSION,
                "schema_version",
                f"schema_version {record.schema_version} is not {SCHEMA_VERSION}",
            )
        )

    return violations


Record = FareObservation | dict[str, object]


def _rebuild(record: Record) -> tuple[FareObservation | None, list[Violation]]:
    """Revalidate one row from its own field values. A built model is dumped first and put
    back through the validators: an instance is not evidence that it was ever validated."""
    values = record.model_dump() if isinstance(record, FareObservation) else record
    try:
        built = FareObservation.model_validate(values)
    except ValidationError as exc:
        return None, [_violation_from_error(error) for error in exc.errors()]
    return built, logical_violations(built)


class _Accumulator:
    """Counts by code and the capped sample, shared by validate_batch and validated_batch."""

    def __init__(self) -> None:
        self.total = 0
        self.invalid = 0
        self.counts: dict[ViolationCode, int] = {}
        self.sample: list[tuple[int, Violation]] = []

    def add(self, index: int, violations: list[Violation]) -> None:
        self.total += 1
        if not violations:
            return
        self.invalid += 1
        for violation in violations:
            self.counts[violation.code] = self.counts.get(violation.code, 0) + 1
            if len(self.sample) < SAMPLE_LIMIT:
                self.sample.append((index, violation))

    def report(self) -> BatchReport:
        return BatchReport(
            total=self.total,
            valid=self.total - self.invalid,
            invalid=self.invalid,
            counts_by_code=self.counts,
            sample=self.sample,
        )


def validate(record: Record) -> list[Violation]:
    """Empty list == valid. Accepts a raw dict (from Parquet) or a built model."""
    return _rebuild(record)[1]


def validate_batch(records: Iterable[Record]) -> BatchReport:
    """Structured report with counts by violation type (SF-03 'What to build' §1)."""
    accumulator = _Accumulator()
    for index, record in enumerate(records):
        accumulator.add(index, validate(record))
    return accumulator.report()


def validated_batch(records: Iterable[Record]) -> list[FareObservation]:
    """Every row, revalidated and rebuilt — or :class:`InvalidBatchError` with the full
    report. This is the trust boundary: the store writes and canonical reconstruction both
    go through it, so no unvalidated instance reaches Parquet or comes back out of it."""
    accumulator = _Accumulator()
    built: list[FareObservation] = []
    for index, record in enumerate(records):
        record_built, violations = _rebuild(record)
        accumulator.add(index, violations)
        if record_built is not None and not violations:
            built.append(record_built)

    report = accumulator.report()
    if not report.ok:
        raise InvalidBatchError(report)
    return built
