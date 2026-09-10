"""Every bad case SF-03 documents, one test each, plus the batch report."""

from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from pipeline.schema import (
    Cabin,
    FareObservation,
    PriceKind,
    Source,
    TripType,
    build_observation,
    validate,
    validate_batch,
)
from pipeline.schema.validation import ViolationCode


def valid_row(**overrides: Any) -> dict[str, Any]:
    """A schema-valid one-way calendar row as a raw dict, with a correct observation_id."""
    record = build_observation(
        source=Source.TRAVELPAYOUTS,
        fetched_at=datetime(2026, 9, 9, 6, 0, tzinfo=UTC),
        origin="JFK",
        destination="LHR",
        depart_date=date(2026, 12, 20),
        trip_type=TripType.ONE_WAY,
        cabin=Cabin.ECONOMY,
        passengers=1,
        amount_minor=42000,
        currency="USD",
        price_kind=PriceKind.CALENDAR_CHEAPEST,
        ingest_run_id="3f6f5b8e-0f2f-5a1c-9f8a-1d2e3f4a5b6c",
    )
    row = record.model_dump()
    row.update(overrides)
    return row


def codes(row: dict[str, Any] | FareObservation) -> set[ViolationCode]:
    return {violation.code for violation in validate(row)}


def test_accepts_a_valid_row_as_dict_and_as_model() -> None:
    row = valid_row()

    assert validate(row) == []
    assert validate(FareObservation.model_validate(row)) == []


def test_rejects_naive_fetched_at() -> None:
    assert ViolationCode.NAIVE_TIMESTAMP in codes(valid_row(fetched_at=datetime(2026, 9, 9, 6, 0)))


def test_rejects_non_utc_fetched_at() -> None:
    offset = timezone(timedelta(hours=2))
    assert ViolationCode.NON_UTC_TIMESTAMP in codes(
        valid_row(fetched_at=datetime(2026, 9, 9, 6, 0, tzinfo=offset))
    )


def test_rejects_lowercase_iata() -> None:
    assert ViolationCode.BAD_IATA in codes(valid_row(origin="jfk"))
    assert ViolationCode.BAD_IATA in codes(valid_row(destination="lhr"))


def test_rejects_two_letter_iata() -> None:
    assert ViolationCode.BAD_IATA in codes(valid_row(origin="JF"))


def test_rejects_lowercase_currency() -> None:
    assert ViolationCode.BAD_CURRENCY in codes(valid_row(currency="usd"))


def test_rejects_route_key_endpoint_mismatch() -> None:
    assert ViolationCode.BAD_ROUTE_KEY in codes(valid_row(route_key="JFK-CDG"))


def test_rejects_zero_amount() -> None:
    assert ViolationCode.NONPOSITIVE_AMOUNT in codes(valid_row(amount_minor=0))


def test_rejects_negative_amount() -> None:
    assert ViolationCode.NONPOSITIVE_AMOUNT in codes(valid_row(amount_minor=-1))


def test_rejects_return_date_on_one_way() -> None:
    assert ViolationCode.RETURN_DATE_MISMATCH in codes(valid_row(return_date=date(2026, 12, 27)))


def test_rejects_missing_return_date_on_round_trip() -> None:
    assert ViolationCode.RETURN_DATE_MISMATCH in codes(valid_row(trip_type="round_trip"))


def test_rejects_unknown_cabin() -> None:
    assert ViolationCode.BAD_ENUM in codes(valid_row(cabin="cattle"))


def test_rejects_unknown_price_kind() -> None:
    assert ViolationCode.BAD_ENUM in codes(valid_row(price_kind="guess"))


def test_rejects_unknown_source() -> None:
    assert ViolationCode.BAD_ENUM in codes(valid_row(source="expedia"))


def test_rejects_unknown_data_quality() -> None:
    assert ViolationCode.BAD_ENUM in codes(valid_row(data_quality="fine"))


def test_rejects_observation_id_mismatch() -> None:
    assert ViolationCode.OBSERVATION_ID_MISMATCH in codes(valid_row(observation_id="dead" * 4))


def test_rejects_wrong_schema_version() -> None:
    assert ViolationCode.BAD_SCHEMA_VERSION in codes(valid_row(schema_version=2))


def test_rejects_missing_required_field() -> None:
    row = valid_row()
    del row["currency"]

    assert ViolationCode.MISSING_REQUIRED in codes(row)


def test_rejects_wrong_type_and_unknown_field() -> None:
    assert ViolationCode.WRONG_TYPE in codes(valid_row(amount_minor="lots"))
    assert ViolationCode.WRONG_TYPE in codes(valid_row(unexpected="nope"))


def test_id_mismatch_is_caught_when_a_key_field_changes() -> None:
    """Changing a natural-key field without recomputing the id is the realistic mistake."""
    assert ViolationCode.OBSERVATION_ID_MISMATCH in codes(valid_row(depart_date=date(2026, 12, 21)))


def test_amount_is_not_part_of_the_natural_key() -> None:
    assert validate(valid_row(amount_minor=999_00)) == []


def test_batch_report_counts_by_code() -> None:
    rows = [
        valid_row(),
        valid_row(amount_minor=0),
        valid_row(currency="usd"),
        valid_row(schema_version=7),
        valid_row(),
    ]

    report = validate_batch(rows)

    assert report.total == 5
    assert report.valid == 2
    assert report.invalid == 3
    assert not report.ok
    assert report.counts_by_code[ViolationCode.NONPOSITIVE_AMOUNT] == 1
    assert report.counts_by_code[ViolationCode.BAD_CURRENCY] == 1
    assert report.counts_by_code[ViolationCode.BAD_SCHEMA_VERSION] == 1
    assert [index for index, _ in report.sample] == [1, 2, 3]


def test_batch_report_is_ok_and_printable_for_clean_input() -> None:
    report = validate_batch([valid_row(), valid_row()])

    assert report.ok
    assert report.counts_by_code == {}
    assert report.sample == []
    assert "2 rows: 2 valid, 0 invalid" in str(report)


def test_batch_report_sample_is_capped_at_twenty() -> None:
    report = validate_batch([valid_row(amount_minor=0) for _ in range(30)])

    assert report.invalid == 30
    assert len(report.sample) == 20
    assert str(report).count("nonpositive_amount") == 21  # 20 sample lines + the counts line


def test_empty_batch_is_ok() -> None:
    report = validate_batch([])

    assert report.total == 0
    assert report.ok


# C2 — the codes the bounded/strict int64 fields and the UUID run id report.


def test_overflowing_amount_is_out_of_range_not_nonpositive() -> None:
    """2**63 used to validate clean and blow up inside Arrow. It is reported as
    out_of_range: only amount_minor's lower bound is a "nonpositive amount"."""
    assert codes(valid_row(amount_minor=2**63)) == {ViolationCode.OUT_OF_RANGE}


def test_zero_amount_is_still_nonpositive() -> None:
    assert ViolationCode.NONPOSITIVE_AMOUNT in codes(valid_row(amount_minor=0))


def test_boolean_amount_is_a_type_violation() -> None:
    assert codes(valid_row(amount_minor=True)) == {ViolationCode.WRONG_TYPE}


def test_integral_float_amount_is_a_type_violation() -> None:
    assert codes(valid_row(amount_minor=42000.0)) == {ViolationCode.WRONG_TYPE}


def test_negative_source_price_age_is_out_of_range() -> None:
    assert codes(valid_row(observed_price_age_seconds=-2)) == {ViolationCode.OUT_OF_RANGE}


def test_rejects_an_ingest_run_id_that_is_not_a_uuid() -> None:
    assert codes(valid_row(ingest_run_id="x/../../../../../escaped")) == {
        ViolationCode.BAD_INGEST_RUN_ID
    }
