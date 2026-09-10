"""The single source of "now" for the whole project.

Nothing else calls ``date.today()`` or ``datetime.now()`` directly (L0 §2 pins every
timestamp to UTC). Setting ``SNAP_TODAY`` pins the project's idea of today, which is what
makes CI and the fixture-anchored tests time-invariant.

Both functions read the override through one parser, so they cannot disagree about what a
given ``SNAP_TODAY`` means: ``today_utc()`` used to parse a date and ``now_utc()`` a
datetime, so ``SNAP_TODAY=2026-09-09T12:34:56`` made the first raise and the second return
12:34:56 UTC — a pin that half-worked (review C4).
"""

import datetime as _dt
import os
import re

SNAP_TODAY_ENV: str = "SNAP_TODAY"

#: The override is a calendar date and nothing else. Checked explicitly rather than left to
#: ``date.fromisoformat``, so the rule is this module's and not an artefact of which ISO
#: spellings the standard library happens to accept in a given Python version.
_DATE_SHAPE: re.Pattern[str] = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _pinned_date() -> _dt.date | None:
    """SNAP_TODAY as a date, or None when it is unset or empty.

    Raises ValueError when it is set but is not an ISO ``YYYY-MM-DD`` date — a typo'd pin
    must fail loudly, not fall back to the clock it was meant to replace, and a
    datetime-shaped value must fail the same way in both public functions.
    """
    raw = os.environ.get(SNAP_TODAY_ENV, "").strip()
    if not raw:
        return None
    if not _DATE_SHAPE.match(raw):
        raise ValueError(
            f"{SNAP_TODAY_ENV}={raw!r} is not an ISO YYYY-MM-DD date "
            "(it pins a calendar date, not an instant)"
        )
    return _dt.date.fromisoformat(raw)


def today_utc() -> _dt.date:
    """The project's definition of "today". Returns SNAP_TODAY parsed as an ISO
    YYYY-MM-DD date when that variable is set and non-empty, otherwise the real UTC
    date. Raises ValueError when SNAP_TODAY is set but unparseable."""
    pinned = _pinned_date()
    if pinned is not None:
        return pinned
    return _dt.datetime.now(_dt.UTC).date()


def now_utc() -> _dt.datetime:
    """Timezone-aware UTC now. When SNAP_TODAY is set, returns that date at
    00:00:00+00:00, so a pinned run has a single fixed instant. Same parse rules,
    same ValueError — the instant is derived from the same date ``today_utc()``
    returns, never parsed separately."""
    pinned = _pinned_date()
    if pinned is not None:
        return _dt.datetime.combine(pinned, _dt.time.min, tzinfo=_dt.UTC)
    return _dt.datetime.now(_dt.UTC)
