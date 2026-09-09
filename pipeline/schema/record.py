"""The canonical fare-observation record (L0 §3).

One row = one price seen for one trip shape, from one source, at one moment in time.
Every producer and consumer in the project imports the model from here; changing it is a
spec-level change.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pipeline.schema.enums import Cabin, DataQuality, PriceKind, QualityFlag, Source, TripType

SCHEMA_VERSION: int = 1

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
    observed_price_age_seconds: int | None = None
    origin: IataCode
    destination: IataCode
    route_key: RouteKey
    depart_date: date
    return_date: date | None = None
    trip_type: TripType
    cabin: Cabin
    passengers: int = Field(ge=1)
    stops_outbound: int | None = Field(default=None, ge=0)
    stops_return: int | None = Field(default=None, ge=0)
    carrier_primary: str | None = Field(default=None, pattern=r"^[A-Z0-9]{2}$")
    amount_minor: int = Field(gt=0)
    currency: CurrencyCode
    price_kind: PriceKind
    data_quality: DataQuality = DataQuality.OK
    quality_flags: list[QualityFlag] | None = None
    ingest_run_id: str
    schema_version: int = SCHEMA_VERSION

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


__all__ = [
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
]
