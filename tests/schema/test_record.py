"""Construction, coercion and nullability of the canonical record (L0 §3)."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from pipeline.schema import Cabin, DataQuality, FareObservation, PriceKind, Source, TripType
from pipeline.schema.record import SCHEMA_VERSION

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
