"""Construction, coercion and nullability of the canonical record (L0 §3)."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from pipeline.schema import Cabin, DataQuality, FareObservation, PriceKind, Source, TripType
from pipeline.schema.record import INT64_MAX, SCHEMA_VERSION

VALID_ID = "0123456789abcdef"


def make_kwargs(**overrides: object) -> dict[str, object]:
    """A minimal valid one-way calendar row; overrides replace individual fields."""
    kwargs: dict[str, object] = {
        "observation_id": VALID_ID,
        "source": "travelpayouts",
        "fetched_at": datetime(2026, 9, 9, 6, 0, tzinfo=UTC),
        "origin": "JFK",
        "destination": "LHR",
        "route_key": "JFK-LHR",
        "depart_date": date(2026, 12, 20),
        "trip_type": "one_way",
        "cabin": "economy",
        "passengers": 1,
        "amount_minor": 42000,
        "currency": "USD",
        "price_kind": "calendar_cheapest",
        "ingest_run_id": "3f6f5b8e-0f2f-5a1c-9f8a-1d2e3f4a5b6c",
    }
    kwargs.update(overrides)
    return kwargs


def test_minimal_row_constructs_with_documented_defaults() -> None:
    obs = FareObservation(**make_kwargs())

    assert obs.source is Source.TRAVELPAYOUTS
    assert obs.trip_type is TripType.ONE_WAY
    assert obs.cabin is Cabin.ECONOMY
    assert obs.price_kind is PriceKind.CALENDAR_CHEAPEST
    assert obs.data_quality is DataQuality.OK
    assert obs.schema_version == SCHEMA_VERSION == 1
    assert obs.return_date is None
    assert obs.quality_flags is None
    assert obs.source_native_id is None
    assert obs.stops_outbound is None
    assert obs.stops_return is None
    assert obs.carrier_primary is None
    assert obs.observed_price_age_seconds is None


def test_strings_coerce_into_enum_members() -> None:
    obs = FareObservation(**make_kwargs(source="fastflights", price_kind="itinerary"))

    assert obs.source is Source.FASTFLIGHTS
    assert obs.source == "fastflights"
    assert obs.price_kind is PriceKind.ITINERARY


def test_frozen_and_extra_forbidden() -> None:
    obs = FareObservation(**make_kwargs())

    with pytest.raises(ValidationError):
        obs.amount_minor = 1  # type: ignore[misc]

    with pytest.raises(ValidationError):
        FareObservation(**make_kwargs(unexpected_field="nope"))


def test_fetched_date_property() -> None:
    early = FareObservation(**make_kwargs(fetched_at=datetime(2026, 9, 9, 0, 30, tzinfo=UTC)))
    late = FareObservation(**make_kwargs(fetched_at=datetime(2026, 9, 9, 23, 30, tzinfo=UTC)))

    assert early.fetched_date == date(2026, 9, 9)
    assert late.fetched_date == date(2026, 9, 9)


def test_zero_offset_timestamp_is_normalised_to_utc() -> None:
    obs = FareObservation(
        **make_kwargs(fetched_at=datetime(2026, 9, 9, 6, 0, tzinfo=timezone(timedelta(0))))
    )

    assert obs.fetched_at.tzinfo is UTC
    assert obs.fetched_date == date(2026, 9, 9)


def test_naive_and_offset_timestamps_are_rejected() -> None:
    with pytest.raises(ValidationError, match="naive_timestamp"):
        FareObservation(**make_kwargs(fetched_at=datetime(2026, 9, 9, 6, 0)))

    with pytest.raises(ValidationError, match="non_utc_timestamp"):
        FareObservation(
            **make_kwargs(
                fetched_at=datetime(2026, 9, 9, 6, 0, tzinfo=timezone(timedelta(hours=2)))
            )
        )


def test_route_key_must_match_endpoints() -> None:
    with pytest.raises(ValidationError, match="bad_route_key"):
        FareObservation(**make_kwargs(route_key="JFK-CDG"))


def test_return_date_is_tied_to_trip_type() -> None:
    with pytest.raises(ValidationError, match="return_date_mismatch"):
        FareObservation(**make_kwargs(return_date=date(2026, 12, 27)))

    with pytest.raises(ValidationError, match="return_date_mismatch"):
        FareObservation(**make_kwargs(trip_type="round_trip"))

    round_trip = FareObservation(
        **make_kwargs(trip_type="round_trip", return_date=date(2026, 12, 27))
    )
    assert round_trip.return_date == date(2026, 12, 27)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("origin", "jfk"),
        ("origin", "JF"),
        ("currency", "usd"),
        ("observation_id", "not-hex-at-all!!"),
        ("carrier_primary", "british"),
        ("amount_minor", 0),
        ("amount_minor", -1),
        ("passengers", 0),
        ("stops_outbound", -1),
        ("source", "expedia"),
        ("cabin", "cattle"),
        ("price_kind", "guess"),
        ("data_quality", "fine"),
    ],
)
def test_field_level_constraints_reject_bad_values(field: str, value: object) -> None:
    kwargs = make_kwargs(**{field: value})
    if field == "origin":
        kwargs["route_key"] = "JFK-LHR"

    with pytest.raises(ValidationError):
        FareObservation(**kwargs)


def test_nullable_fields_accept_values() -> None:
    obs = FareObservation(
        **make_kwargs(
            source="fastflights",
            price_kind="itinerary",
            source_native_id="ff-0123456789",
            observed_price_age_seconds=3600,
            stops_outbound=0,
            carrier_primary="BA",
            quality_flags=["price_below_floor"],
        )
    )

    assert obs.source_native_id == "ff-0123456789"
    assert obs.observed_price_age_seconds == 3600
    assert obs.stops_outbound == 0
    assert obs.carrier_primary == "BA"
    assert obs.quality_flags is not None
    assert obs.quality_flags[0] == "price_below_floor"


# C2 — int64-backed fields are bounded and strict, and ingest_run_id is a UUID.


@pytest.mark.parametrize(
    "field",
    ["amount_minor", "passengers", "observed_price_age_seconds", "stops_outbound", "stops_return"],
)
def test_rejects_boolean_for_an_int64_field(field: str) -> None:
    """bool is an int subclass; True must not become a price of 1 or a passenger count."""
    with pytest.raises(ValidationError):
        FareObservation(**make_kwargs(**{field: True}))


@pytest.mark.parametrize("field", ["amount_minor", "passengers", "stops_outbound"])
def test_rejects_integral_float_for_an_int64_field(field: str) -> None:
    with pytest.raises(ValidationError):
        FareObservation(**make_kwargs(**{field: 1.0}))


@pytest.mark.parametrize(
    "field",
    ["amount_minor", "passengers", "observed_price_age_seconds", "stops_outbound", "stops_return"],
)
def test_rejects_a_value_above_int64_max(field: str) -> None:
    """Used to construct, then raise OverflowError during Arrow conversion — after
    earlier partition groups had already been written."""
    with pytest.raises(ValidationError):
        FareObservation(**make_kwargs(**{field: INT64_MAX + 1}))


def test_rejects_negative_observed_price_age() -> None:
    with pytest.raises(ValidationError):
        FareObservation(**make_kwargs(observed_price_age_seconds=-2))


def test_accepts_zero_observed_price_age() -> None:
    assert (
        FareObservation(**make_kwargs(observed_price_age_seconds=0)).observed_price_age_seconds == 0
    )


def test_accepts_int64_max_amount() -> None:
    assert FareObservation(**make_kwargs(amount_minor=INT64_MAX)).amount_minor == INT64_MAX


@pytest.mark.parametrize(
    "run_id",
    [
        "run-1",
        "",
        "x/../../../../../escaped",
        "3f6f5b8e-0f2f-5a1c-9f8a-1d2e3f4a5b6",
    ],
)
def test_rejects_an_ingest_run_id_that_is_not_a_uuid(run_id: str) -> None:
    with pytest.raises(ValidationError):
        FareObservation(**make_kwargs(ingest_run_id=run_id))


def test_ingest_run_id_is_canonicalised() -> None:
    """Braces, uppercase and the unhyphenated form all name the same run; the store's
    dedup tiebreaker and its file names need one spelling."""
    canonical = "3f6f5b8e-0f2f-5a1c-9f8a-1d2e3f4a5b6c"
    for spelling in (canonical.upper(), canonical.replace("-", ""), "{" + canonical + "}"):
        assert FareObservation(**make_kwargs(ingest_run_id=spelling)).ingest_run_id == canonical
