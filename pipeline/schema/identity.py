"""Natural key canonicalisation and the deterministic observation id (L0 §2, §6).

L0 §6 gives the rule — ``sha256(natural key fields joined with "|")[:16]`` — but not the
encoding. It is pinned here (SF-03-build §2.3) and asserted against five fixed vectors:

* field order is exactly L0 §6's list;
* ``None`` encodes as the empty string;
* dates encode as ISO ``YYYY-MM-DD``, ints as base-10 with no padding;
* strings and enums encode verbatim, already normalised (IATA upper, cabin lower);
* fields are joined with ``|`` and there is no trailing separator;
* the hash is SHA-256 over the UTF-8 bytes, lowercase hex, first 16 characters.

``fetched_date`` — the UTC calendar date of ``fetched_at``, never the timestamp — is what
makes collection idempotent within a day.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import TYPE_CHECKING

from pipeline.schema.enums import Cabin, PriceKind, Source, TripType

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, record.py imports this module
    from pipeline.schema.record import FareObservation

NATURAL_KEY_FIELDS: tuple[str, ...] = (
    "source",
    "origin",
    "destination",
    "depart_date",
    "return_date",
    "cabin",
    "passengers",
    "trip_type",
    "stops_outbound",
    "stops_return",
    "carrier_primary",
    "price_kind",
    "fetched_date",
)

SEPARATOR: str = "|"


def _encode(value: object) -> str:
    """One natural-key field as its canonical string (SF-03-build §2.3)."""
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):  # bool is an int subclass; it has no place in the key
        raise TypeError("natural-key fields are never booleans")
    if isinstance(value, int):
        return str(value)
    return str(value)


def natural_key(
    *,
    source: Source | str,
    origin: str,
    destination: str,
    depart_date: date,
    return_date: date | None,
    cabin: Cabin | str,
    passengers: int,
    trip_type: TripType | str,
    stops_outbound: int | None,
    stops_return: int | None,
    carrier_primary: str | None,
    price_kind: PriceKind | str,
    fetched_date: date,
) -> str:
    """The canonical join string. Exposed for debugging and for the fixed-vector tests."""
    values = (
        source,
        origin,
        destination,
        depart_date,
        return_date,
        cabin,
        passengers,
        trip_type,
        stops_outbound,
        stops_return,
        carrier_primary,
        price_kind,
        fetched_date,
    )
    return SEPARATOR.join(_encode(value) for value in values)


def observation_id(**natural_key_fields: object) -> str:
    """``sha256(natural_key(...))[:16]``. Same kwargs as :func:`natural_key`."""
    canonical = natural_key(**natural_key_fields)  # type: ignore[arg-type]
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def observation_id_for(record: FareObservation) -> str:
    """Recompute the id from a record's own fields — used by ``validate()``."""
    return observation_id(
        source=record.source,
        origin=record.origin,
        destination=record.destination,
        depart_date=record.depart_date,
        return_date=record.return_date,
        cabin=record.cabin,
        passengers=record.passengers,
        trip_type=record.trip_type,
        stops_outbound=record.stops_outbound,
        stops_return=record.stops_return,
        carrier_primary=record.carrier_primary,
        price_kind=record.price_kind,
        fetched_date=record.fetched_date,
    )
