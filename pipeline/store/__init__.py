"""The append-only snapshot store — the only way models and the API get fare data (L0 §6)."""

from pipeline.schema.validation import InvalidBatchError
from pipeline.store.filters import ReadFilters
from pipeline.store.snapshot_store import (
    FRAME_SCHEMA,
    SnapshotStore,
    WriteResult,
    default_store,
)

__all__ = [
    "FRAME_SCHEMA",
    "InvalidBatchError",
    "ReadFilters",
    "SnapshotStore",
    "WriteResult",
    "default_store",
]
