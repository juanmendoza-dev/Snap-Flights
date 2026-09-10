"""The canonical fare-observation schema — the single source of truth (L0 §3)."""

from pipeline.schema.arrow import (
    COLUMN_ORDER,
    FARE_OBSERVATION_ARROW_SCHEMA,
    records_to_table,
    table_to_records,
)
from pipeline.schema.enums import (
    Cabin,
    DataQuality,
    PriceKind,
    QualityFlag,
    Source,
    TripType,
)
from pipeline.schema.identity import NATURAL_KEY_FIELDS, natural_key, observation_id
from pipeline.schema.record import (
    SCHEMA_VERSION,
    FareObservation,
    build_observation,
    with_quality,
)
from pipeline.schema.validation import (
    BatchReport,
    InvalidBatchError,
    Violation,
    ViolationCode,
    validate,
    validate_batch,
    validated_batch,
)

__all__ = [
    "COLUMN_ORDER",
    "FARE_OBSERVATION_ARROW_SCHEMA",
    "NATURAL_KEY_FIELDS",
    "SCHEMA_VERSION",
    "BatchReport",
    "Cabin",
    "DataQuality",
    "FareObservation",
    "InvalidBatchError",
    "PriceKind",
    "QualityFlag",
    "Source",
    "TripType",
    "Violation",
    "ViolationCode",
    "build_observation",
    "natural_key",
    "observation_id",
    "records_to_table",
    "table_to_records",
    "validate",
    "validate_batch",
    "validated_batch",
    "with_quality",
]
