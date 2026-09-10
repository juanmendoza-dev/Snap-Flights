"""Read filters for the snapshot store (SF-03-build §2.7).

Everything a caller can express is checked here, at construction, rather than by DuckDB
halfway through a query (review C3). An empty selection is a legitimate request — "give me
these zero routes" — and answers with an empty result, not a parser exception; a reversed
range, a negative limit, a naive cutoff or a malformed route key are mistakes, and say so.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pipeline.schema.enums import DataQuality, PriceKind, Source

RouteKeyFilter = Annotated[str, Field(pattern=r"^[A-Z]{3}-[A-Z]{3}$")]
Limit = Annotated[int, Field(strict=True, ge=0)]


class ReadFilters(BaseModel):
    """Every filter is AND-ed. None means 'no constraint on this dimension'.
    Date/timestamp ranges are inclusive on both ends. An empty list means 'nothing
    matches' and returns an empty result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Source | Sequence[Source] | None = None
    route_key: RouteKeyFilter | Sequence[RouteKeyFilter] | None = None
    fetched_date_from: date | None = None
    fetched_date_to: date | None = None
    fetched_at_from: datetime | None = None
    fetched_at_to: datetime | None = None
    depart_date_from: date | None = None
    depart_date_to: date | None = None
    price_kind: PriceKind | Sequence[PriceKind] | None = None
    data_quality: DataQuality | Sequence[DataQuality] | None = None
    include_rejected: bool = False
    limit: Limit | None = None

    @field_validator("fetched_at_from", "fetched_at_to")
    @classmethod
    def _cutoff_is_utc_aware(cls, v: datetime | None) -> datetime | None:
        """Same contract as the record's own fetched_at (L0 §0): tz-aware UTC or an error.

        The query runs under a UTC session, so a naive local cutoff used to be silently
        reinterpreted as UTC — a caller in New York asking for "since 09:00" quietly got
        five hours of extra history.
        """
        if v is None:
            return None
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("naive_timestamp: fetched_at filters must be timezone-aware UTC")
        if v.utcoffset() != timedelta(0):
            raise ValueError(f"non_utc_timestamp: filter offset is {v.utcoffset()}, not UTC")
        return v.astimezone(UTC)

    @model_validator(mode="after")
    def _ranges_are_ordered(self) -> ReadFilters:
        for name, low, high in (
            ("fetched_date", self.fetched_date_from, self.fetched_date_to),
            ("fetched_at", self.fetched_at_from, self.fetched_at_to),
            ("depart_date", self.depart_date_from, self.depart_date_to),
        ):
            if low is not None and high is not None and low > high:
                raise ValueError(f"reversed_range: {name}_from ({low}) is after {name}_to ({high})")
        return self

    @property
    def selects_nothing(self) -> bool:
        """True when some dimension was given an explicitly empty list.

        `route_key=[]` is a scheduler or model asking about zero routes, which used to
        build `IN ()` and raise a DuckDB ParserException — but only once the store had
        data, so the failure mode depended on whether anything had been collected yet.
        """
        return any(
            as_list(value) == []
            for value in (self.source, self.route_key, self.price_kind, self.data_quality)
        )


def as_list(value: object) -> list[str] | None:
    """Normalise a scalar-or-sequence filter to a list of plain strings, or None."""
    if value is None:
        return None
    if isinstance(value, str):
        return [str(value)]
    if isinstance(value, Sequence):
        return [str(item) for item in value]
    return [str(value)]
