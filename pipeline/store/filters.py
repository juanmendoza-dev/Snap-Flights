"""Read filters for the snapshot store (SF-03-build §2.7)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from pipeline.schema.enums import DataQuality, PriceKind, Source


class ReadFilters(BaseModel):
    """Every filter is AND-ed. None means 'no constraint on this dimension'.
    Date/timestamp ranges are inclusive on both ends."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Source | Sequence[Source] | None = None
    route_key: str | Sequence[str] | None = None
    fetched_date_from: date | None = None
    fetched_date_to: date | None = None
    fetched_at_from: datetime | None = None
    fetched_at_to: datetime | None = None
    depart_date_from: date | None = None
    depart_date_to: date | None = None
    price_kind: PriceKind | Sequence[PriceKind] | None = None
    data_quality: DataQuality | Sequence[DataQuality] | None = None
    include_rejected: bool = False
    limit: int | None = None


def as_list(value: object) -> list[str] | None:
    """Normalise a scalar-or-sequence filter to a list of plain strings, or None."""
    if value is None:
        return None
    if isinstance(value, str):
        return [str(value)]
    if isinstance(value, Sequence):
        return [str(item) for item in value]
    return [str(value)]
