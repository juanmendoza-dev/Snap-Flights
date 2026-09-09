"""Helpers shared by the snapshot-store tests.

They live in the package ``__init__`` rather than a ``conftest.py`` because SF-03-build §1
pins the test tree exactly: ``tests/store/`` holds ``__init__.py``, ``test_write.py``,
``test_read.py`` and ``test_fixture_mode.py``, and nothing else.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from pipeline.schema import (
    Cabin,
    DataQuality,
    FareObservation,
    PriceKind,
    Source,
    TripType,
    build_observation,
)
from pipeline.store import SnapshotStore
from shared.settings import load_data_settings

RUN_A: str = "11111111-1111-5111-8111-111111111111"
RUN_B: str = "22222222-2222-5222-8222-222222222222"


def make_observation(
    *,
    route_key: str = "JFK-LHR",
    source: Source = Source.TRAVELPAYOUTS,
    fetched_at: datetime | None = None,
    depart_date: date = date(2026, 12, 20),
    amount_minor: int = 42000,
    price_kind: PriceKind = PriceKind.CALENDAR_CHEAPEST,
    ingest_run_id: str = RUN_A,
    data_quality: DataQuality = DataQuality.OK,
    stops_outbound: int | None = None,
    carrier_primary: str | None = None,
) -> FareObservation:
    """A schema-valid one-way economy row with everything but the varied fields fixed."""
    origin, destination = route_key.split("-")
    return build_observation(
        source=source,
        fetched_at=fetched_at if fetched_at is not None else datetime(2026, 9, 9, 6, 0, tzinfo=UTC),
        origin=origin,
        destination=destination,
        depart_date=depart_date,
        trip_type=TripType.ONE_WAY,
        cabin=Cabin.ECONOMY,
        passengers=1,
        amount_minor=amount_minor,
        currency="USD",
        price_kind=price_kind,
        ingest_run_id=ingest_run_id,
        data_quality=data_quality,
        stops_outbound=stops_outbound,
        carrier_primary=carrier_primary,
    )


def store_at(root: Path, *, use_fixtures: bool = False) -> SnapshotStore:
    """A store rooted at a temporary directory, never at the real repo."""
    return SnapshotStore(load_data_settings(repo_root=root, use_fixtures=use_fixtures))
