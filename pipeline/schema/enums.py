"""The closed enum vocabularies of the canonical schema (L0 §2, §3)."""

from enum import StrEnum


class Source(StrEnum):
    TRAVELPAYOUTS = "travelpayouts"
    FASTFLIGHTS = "fastflights"


class TripType(StrEnum):
    ONE_WAY = "one_way"
    ROUND_TRIP = "round_trip"


class Cabin(StrEnum):
    ECONOMY = "economy"
    PREMIUM_ECONOMY = "premium_economy"
    BUSINESS = "business"
    FIRST = "first"


class PriceKind(StrEnum):
    ITINERARY = "itinerary"
    CALENDAR_CHEAPEST = "calendar_cheapest"


class DataQuality(StrEnum):
    OK = "ok"
    SUSPECT = "suspect"
    REJECTED = "rejected"


class QualityFlag(StrEnum):
    """Flag vocabulary is owned by SF-05 (skipped this pass); the enum is declared here
    because ``quality_flags`` is a schema field. SF-05 may add members, never rename."""

    SCHEMA_INVALID = "schema_invalid"
    NONPOSITIVE_PRICE = "nonpositive_price"
    PRICE_ABOVE_CEILING = "price_above_ceiling"
    PRICE_BELOW_FLOOR = "price_below_floor"
    PRICE_ZSCORE_EXTREME = "price_zscore_extreme"
    STALE_SOURCE_PRICE = "stale_source_price"
    IMPOSSIBLE_DATES = "impossible_dates"
    UNKNOWN_AIRPORT = "unknown_airport"
