"""Row and batch validation for the canonical schema (SF-03 'What to build' §1).

``validate()`` accepts either a built :class:`FareObservation` or a raw dict straight off
Parquet, and returns a list of :class:`Violation` — empty means valid. Most field-level
rules live on the Pydantic model; this module maps a pydantic error back to a stable
``ViolationCode`` so a batch report can count violations by kind rather than by prose.

Two rules cannot live on the model and are checked here: the ``observation_id`` must
recompute from the record's own natural key (L0 §2), and ``schema_version`` must be the
version this code speaks.
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


def _post_construction_violations(record: FareObservation) -> list[Violation]:
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


def validate(record: FareObservation | dict[str, object]) -> list[Violation]:
    """Empty list == valid. Accepts a raw dict (from Parquet) or a built model."""
    if isinstance(record, FareObservation):
        return _post_construction_violations(record)

    try:
        built = FareObservation.model_validate(record)
    except ValidationError as exc:
        return [_violation_from_error(error) for error in exc.errors()]

    return _post_construction_violations(built)


def validate_batch(records: Iterable[FareObservation | dict[str, object]]) -> BatchReport:
    """Structured report with counts by violation type (SF-03 'What to build' §1)."""
    total = 0
    invalid = 0
    counts: dict[ViolationCode, int] = {}
    sample: list[tuple[int, Violation]] = []

    for index, record in enumerate(records):
        total += 1
        violations = validate(record)
        if not violations:
            continue
        invalid += 1
        for violation in violations:
            counts[violation.code] = counts.get(violation.code, 0) + 1
            if len(sample) < SAMPLE_LIMIT:
                sample.append((index, violation))

    return BatchReport(
        total=total,
        valid=total - invalid,
        invalid=invalid,
        counts_by_code=counts,
        sample=sample,
    )
