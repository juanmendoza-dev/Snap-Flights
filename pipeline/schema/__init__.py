"""The canonical fare-observation schema — the single source of truth (L0 §3)."""

from pipeline.schema.enums import (
    Cabin,
    DataQuality,
    PriceKind,
    QualityFlag,
    Source,
    TripType,
)
from pipeline.schema.identity import NATURAL_KEY_FIELDS, natural_key, observation_id
from pipeline.schema.record import SCHEMA_VERSION, FareObservation, build_observation

__all__ = [
    "NATURAL_KEY_FIELDS",
    "SCHEMA_VERSION",
    "Cabin",
    "DataQuality",
    "FareObservation",
    "PriceKind",
    "QualityFlag",
    "Source",
    "TripType",
    "build_observation",
    "natural_key",
    "observation_id",
]
