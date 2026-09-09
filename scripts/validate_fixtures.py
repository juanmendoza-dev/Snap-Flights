"""Validate the committed fixture dataset against the canonical schema.

Skeleton only: P0 creates the entry point and wires it into CI, SF-03 writes the body
once `pipeline/schema/` and the fixture Parquet exist.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / "data" / "fixtures" / "fare_observations.parquet"


def main(argv: list[str] | None = None) -> int:
    """Validate every row of data/fixtures/fare_observations.parquet against the
    canonical schema. Returns 0 on success, 1 on any violation, 0 with a printed
    skip notice when the fixture file does not exist yet (P0 state)."""
    if not FIXTURE_PATH.exists():
        print(
            f"skip: {FIXTURE_PATH.relative_to(REPO_ROOT)} does not exist yet — nothing to validate"
        )
        return 0

    raise NotImplementedError("fixture validation lands with SF-03")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
