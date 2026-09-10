"""The canonical fare-observation record (L0 §3).

One row = one price seen for one trip shape, from one source, at one moment in time.
Every producer and consumer in the project imports the model from here; changing it is a
spec-level change.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pipeline.schema.enums import Cabin, DataQuality, PriceKind, QualityFlag, Source, TripType
from pipeline.schema.identity import observation_id

SCHEMA_VERSION: int = 1

#: Every int64-backed field is bounded by the physical Arrow type, not by Python's
#: unbounded int: an out-of-range value used to validate here and raise OverflowError
#: during Arrow conversion, after earlier partition groups had already been written.
#: ``strict`` additionally rejects ``True``/``1.0`` for a count or an amount.
INT64_MAX: int = 2**63 - 1

Count = Annotated[int, Field(strict=True, ge=0, le=INT64_MAX)]
PositiveCount = Annotated[int, Field(strict=True, ge=1, le=INT64_MAX)]
AmountMinor = Annotated[int, Field(strict=True, gt=0, le=INT64_MAX)]
SchemaVersion = Annotated[int, Field(strict=True, ge=1, le=INT64_MAX)]

IataCode = Annotated[str, Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")]
RouteKey = Annotated[str, Field(min_length=7, max_length=7, pattern=r"^[A-Z]{3}-[A-Z]{3}$")]
CurrencyCode = Annotated[str, Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")]
ObservationId = Annotated[str, Field(min_length=16, max_length=16, pattern=r"^[0-9a-f]{16}$")]


class FareObservation(BaseModel):
    """One price, one trip shape, one source, one moment (L0 §3)."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    observation_id: ObservationId
    source: Source
    source_native_id: str | None = None
    fetched_at: datetime
    observed_price_age_seconds: Count | None = None
    origin: IataCode
    destination: IataCode
    route_key: RouteKey
    depart_date: date
    return_date: date | None = None
    trip_type: TripType
    cabin: Cabin
    passengers: PositiveCount
    stops_outbound: Count | None = None
    stops_return: Count | None = None
    carrier_primary: str | None = Field(default=None, pattern=r"^[A-Z0-9]{2}$")
    amount_minor: AmountMinor
    currency: CurrencyCode
    price_kind: PriceKind
    data_quality: DataQuality = DataQuality.OK
    quality_flags: list[QualityFlag] | None = None
    ingest_run_id: str
    schema_version: SchemaVersion = SCHEMA_VERSION

    @field_validator("fetched_at")
    @classmethod
    def _fetched_at_is_utc_aware(cls, v: datetime) -> datetime:
        """tz-aware and UTC (L0 §0). A naive datetime is an error, not something to guess at.

        The leading token of each message is a ``ViolationCode`` value so ``validate()`` can
        map the pydantic error back to a code without matching on prose.
        """
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("naive_timestamp: fetched_at must be timezone-aware UTC")
        if v.utcoffset() != timedelta(0):
            raise ValueError(f"non_utc_timestamp: fetched_at offset is {v.utcoffset()}, not UTC")
        return v.astimezone(UTC)

    @field_validator("ingest_run_id")
    @classmethod
    def _ingest_run_id_is_a_uuid(cls, v: str) -> str:
        """L0 §3 types ingest_run_id as a uuid, and L0 §6 puts it straight into a file
        name. Parse it and keep the canonical lowercase-hyphenated form, so the dedup
        tiebreaker orders on one spelling and a run id can never carry a path separator."""
        try:
            parsed = UUID(v)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError(f"bad_ingest_run_id: ingest_run_id {v!r} is not a UUID") from exc
        return str(parsed)

    @model_validator(mode="after")
    def _route_key_matches_endpoints(self) -> FareObservation:
        expected = f"{self.origin}-{self.destination}"
        if self.route_key != expected:
            raise ValueError(
                f"bad_route_key: route_key {self.route_key!r} does not match "
                f"origin/destination ({expected!r})"
            )
        return self

    @model_validator(mode="after")
    def _return_date_iff_round_trip(self) -> FareObservation:
        """return_date is null iff trip_type == one_way (SF-03 'What to build' §1)."""
        if self.trip_type is TripType.ONE_WAY and self.return_date is not None:
            raise ValueError(
                "return_date_mismatch: a one_way observation cannot have a return_date"
            )
        if self.trip_type is TripType.ROUND_TRIP and self.return_date is None:
            raise ValueError("return_date_mismatch: a round_trip observation needs a return_date")
        return self

    @property
    def fetched_date(self) -> date:
        """UTC calendar date of fetched_at — the partition key and a natural-key field (L0 §6)."""
        return self.fetched_at.astimezone(UTC).date()


def build_observation(
    *,
    source: Source,
    fetched_at: datetime,
    origin: str,
    destination: str,
    depart_date: date,
    trip_type: TripType,
    cabin: Cabin,
    passengers: int,
    amount_minor: int,
    currency: str,
    price_kind: PriceKind,
    ingest_run_id: str,
    return_date: date | None = None,
    stops_outbound: int | None = None,
    stops_return: int | None = None,
    carrier_primary: str | None = None,
    source_native_id: str | None = None,
    observed_price_age_seconds: int | None = None,
    data_quality: DataQuality = DataQuality.OK,
    quality_flags: list[QualityFlag] | None = None,
) -> FareObservation:
    """Derive route_key and observation_id, then construct. The only sanctioned way to
    create a FareObservation from source data."""
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise ValueError("naive_timestamp: fetched_at must be timezone-aware UTC")
    fetched_date = fetched_at.astimezone(UTC).date()
    route_key = f"{origin}-{destination}"
    return FareObservation(
        observation_id=observation_id(
            source=source,
            origin=origin,
            destination=destination,
            depart_date=depart_date,
            return_date=return_date,
            cabin=cabin,
            passengers=passengers,
            trip_type=trip_type,
            stops_outbound=stops_outbound,
            stops_return=stops_return,
            carrier_primary=carrier_primary,
            price_kind=price_kind,
            fetched_date=fetched_date,
        ),
        source=source,
        source_native_id=source_native_id,
        fetched_at=fetched_at,
        observed_price_age_seconds=observed_price_age_seconds,
        origin=origin,
        destination=destination,
        route_key=route_key,
        depart_date=depart_date,
        return_date=return_date,
        trip_type=trip_type,
        cabin=cabin,
        passengers=passengers,
        stops_outbound=stops_outbound,
        stops_return=stops_return,
        carrier_primary=carrier_primary,
        amount_minor=amount_minor,
        currency=currency,
        price_kind=price_kind,
        data_quality=data_quality,
        quality_flags=quality_flags,
        ingest_run_id=ingest_run_id,
    )


__all__ = [
    "INT64_MAX",
    "SCHEMA_VERSION",
    "Cabin",
    "CurrencyCode",
    "DataQuality",
    "FareObservation",
    "IataCode",
    "ObservationId",
    "PriceKind",
    "QualityFlag",
    "RouteKey",
    "Source",
    "TripType",
    "build_observation",
]
