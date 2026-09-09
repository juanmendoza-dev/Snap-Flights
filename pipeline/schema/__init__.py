"""The canonical fare-observation schema — the single source of truth (L0 §3)."""

from pipeline.schema.enums import (
    Cabin,
    DataQuality,
    PriceKind,
    QualityFlag,
    Source,
    TripType,
)
from pipeline.schema.record import SCHEMA_VERSION, FareObservation

__all__ = [
    "SCHEMA_VERSION",
    "Cabin",
    "DataQuality",
    "FareObservation",
    "PriceKind",
    "QualityFlag",
    "Source",
    "TripType",
]
