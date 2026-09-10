"""The pinned natural-key canonicalisation and its five fixed vectors (SF-03-build §2.3)."""

import inspect
import os
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from pipeline.schema import NATURAL_KEY_FIELDS, natural_key, observation_id
from pipeline.schema.enums import Cabin, PriceKind, Source, TripType
from pipeline.schema.identity import observation_id_for
from pipeline.schema.record import build_observation

# ingest_run_id is not a natural-key field; it only has to be a UUID (L0 §3).
RUN_ID: str = "11111111-1111-5111-8111-111111111111"

# (kwargs, canonical string, observation id) — the table in SF-03-build §2.3, verbatim.
FIXED_VECTORS: tuple[tuple[dict[str, object], str, str], ...] = (
    (
        {
            "source": "travelpayouts",
            "origin": "JFK",
            "destination": "LHR",
            "depart_date": date(2026, 12, 20),
            "return_date": None,
            "cabin": "economy",
            "passengers": 1,
            "trip_type": "one_way",
            "stops_outbound": None,
            "stops_return": None,
            "carrier_primary": None,
            "price_kind": "calendar_cheapest",
            "fetched_date": date(2026, 9, 9),
        },
        "travelpayouts|JFK|LHR|2026-12-20||economy|1|one_way||||calendar_cheapest|2026-09-09",
        "5477078824fd0f61",
    ),
    (
        {
            "source": "fastflights",
            "origin": "JFK",
            "destination": "LHR",
            "depart_date": date(2026, 12, 20),
            "return_date": None,
            "cabin": "economy",
            "passengers": 1,
            "trip_type": "one_way",
            "stops_outbound": 0,
            "stops_return": None,
            "carrier_primary": "BA",
            "price_kind": "itinerary",
            "fetched_date": date(2026, 9, 9),
        },
        "fastflights|JFK|LHR|2026-12-20||economy|1|one_way|0||BA|itinerary|2026-09-09",
        "c518122f90afdbd8",
    ),
    (
        {
            "source": "travelpayouts",
            "origin": "MAD",
            "destination": "LIS",
            "depart_date": date(2027, 1, 7),
            "return_date": None,
            "cabin": "economy",
            "passengers": 1,
            "trip_type": "one_way",
            "stops_outbound": None,
            "stops_return": None,
            "carrier_primary": None,
            "price_kind": "calendar_cheapest",
            "fetched_date": date(2026, 6, 12),
        },
        "travelpayouts|MAD|LIS|2027-01-07||economy|1|one_way||||calendar_cheapest|2026-06-12",
        "09af5365f2a6bff9",
    ),
    (
        {
            "source": "fastflights",
            "origin": "LAX",
            "destination": "NRT",
            "depart_date": date(2026, 10, 1),
            "return_date": None,
            "cabin": "economy",
            "passengers": 1,
            "trip_type": "one_way",
            "stops_outbound": 1,
            "stops_return": None,
            "carrier_primary": "NH",
            "price_kind": "itinerary",
            "fetched_date": date(2026, 8, 15),
        },
        "fastflights|LAX|NRT|2026-10-01||economy|1|one_way|1||NH|itinerary|2026-08-15",
        "911acecfc2b32add",
    ),
    (
        {
            "source": "travelpayouts",
            "origin": "LHR",
            "destination": "JFK",
            "depart_date": date(2026, 11, 3),
            "return_date": date(2026, 11, 10),
            "cabin": "business",
            "passengers": 2,
            "trip_type": "round_trip",
            "stops_outbound": 0,
            "stops_return": 1,
            "carrier_primary": "VS",
            "price_kind": "itinerary",
            "fetched_date": date(2026, 9, 9),
        },
        "travelpayouts|LHR|JFK|2026-11-03|2026-11-10|business|2|round_trip|0|1|VS|itinerary"
        "|2026-09-09",
        "95952155f6787ec0",
    ),
)


@pytest.mark.parametrize(("kwargs", "canonical", "expected_id"), FIXED_VECTORS)
def test_fixed_vectors(kwargs: dict[str, object], canonical: str, expected_id: str) -> None:
    assert natural_key(**kwargs) == canonical
    assert observation_id(**kwargs) == expected_id


def test_null_fields_encode_as_empty_string() -> None:
    kwargs, canonical, _ = FIXED_VECTORS[0]

    assert canonical == natural_key(**kwargs)
    assert natural_key(**kwargs).split("|") == [
        "travelpayouts",
        "JFK",
        "LHR",
        "2026-12-20",
        "",
        "economy",
        "1",
        "one_way",
        "",
        "",
        "",
        "calendar_cheapest",
        "2026-09-09",
    ]


def test_field_order_matches_l0_section_6() -> None:
    assert NATURAL_KEY_FIELDS == (
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

    signature = inspect.signature(natural_key)
    assert tuple(signature.parameters) == NATURAL_KEY_FIELDS
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in signature.parameters.values())


def test_no_trailing_separator_and_every_field_present() -> None:
    for kwargs, canonical, _ in FIXED_VECTORS:
        assert not canonical.endswith("|")
        assert len(natural_key(**kwargs).split("|")) == len(NATURAL_KEY_FIELDS)


def test_distinct_sources_give_distinct_ids() -> None:
    first, second = FIXED_VECTORS[0], FIXED_VECTORS[1]

    assert first[0]["depart_date"] == second[0]["depart_date"]
    assert first[0]["fetched_date"] == second[0]["fetched_date"]
    assert observation_id(**first[0]) != observation_id(**second[0])

    only_source = dict(first[0], source="fastflights")
    assert observation_id(**only_source) != observation_id(**first[0])


def test_enum_members_and_their_string_values_agree() -> None:
    kwargs = dict(FIXED_VECTORS[1][0])
    typed = dict(
        kwargs,
        source=Source.FASTFLIGHTS,
        cabin=Cabin.ECONOMY,
        trip_type=TripType.ONE_WAY,
        price_kind=PriceKind.ITINERARY,
    )

    assert natural_key(**typed) == FIXED_VECTORS[1][1]
    assert observation_id(**typed) == FIXED_VECTORS[1][2]


def test_id_is_sixteen_lowercase_hex_characters() -> None:
    for kwargs, _, _ in FIXED_VECTORS:
        value = observation_id(**kwargs)
        assert len(value) == 16
        assert value == value.lower()
        int(value, 16)


def test_observation_id_for_recomputes_from_a_record() -> None:
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
        ingest_run_id=RUN_ID,
    )

    assert record.observation_id == FIXED_VECTORS[0][2]
    assert observation_id_for(record) == record.observation_id


def test_fetched_at_time_of_day_does_not_change_the_id() -> None:
    kwargs: dict[str, object] = dict(
        source=Source.TRAVELPAYOUTS,
        origin="JFK",
        destination="LHR",
        depart_date=date(2026, 12, 20),
        trip_type=TripType.ONE_WAY,
        cabin=Cabin.ECONOMY,
        passengers=1,
        amount_minor=42000,
        currency="USD",
        price_kind=PriceKind.CALENDAR_CHEAPEST,
        ingest_run_id=RUN_ID,
    )
    morning = build_observation(fetched_at=datetime(2026, 9, 9, 6, 0, tzinfo=UTC), **kwargs)
    midnight = build_observation(fetched_at=datetime(2026, 9, 9, 23, 59, tzinfo=UTC), **kwargs)

    assert morning.observation_id == midnight.observation_id == FIXED_VECTORS[0][2]


def test_stable_across_processes(repo_root: Path) -> None:
    """A fresh interpreter with a randomised hash seed must produce the same ids."""
    script = (
        "from datetime import date;"
        "from pipeline.schema import observation_id;"
        "print(observation_id(source='travelpayouts', origin='JFK', destination='LHR',"
        " depart_date=date(2026, 12, 20), return_date=None, cabin='economy', passengers=1,"
        " trip_type='one_way', stops_outbound=None, stops_return=None, carrier_primary=None,"
        " price_kind='calendar_cheapest', fetched_date=date(2026, 9, 9)))"
    )
    env = dict(os.environ, PYTHONHASHSEED="random", PYTHONPATH=str(repo_root))

    outputs = {
        subprocess.run(
            [sys.executable, "-c", script],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        for _ in range(3)
    }

    assert outputs == {"5477078824fd0f61"}
