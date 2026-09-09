"""The single source of "now" for the whole project.

Nothing else calls ``date.today()`` or ``datetime.now()`` directly (L0 §2 pins every
timestamp to UTC). Setting ``SNAP_TODAY`` pins the project's idea of today, which is what
makes CI and the fixture-anchored tests time-invariant.
"""

import datetime as _dt
import os

SNAP_TODAY_ENV: str = "SNAP_TODAY"


def today_utc() -> _dt.date:
    """The project's definition of "today". Returns SNAP_TODAY parsed as an ISO
    YYYY-MM-DD date when that variable is set and non-empty, otherwise the real UTC
    date. Raises ValueError when SNAP_TODAY is set but unparseable — a typo'd pin
    must fail loudly, not fall back to the clock it was meant to replace."""
    raw = os.environ.get(SNAP_TODAY_ENV, "").strip()
    if raw:
        return _dt.date.fromisoformat(raw)
    return _dt.datetime.now(_dt.UTC).date()


def now_utc() -> _dt.datetime:
    """Timezone-aware UTC now. When SNAP_TODAY is set, returns that date at
    00:00:00+00:00, so a pinned run has a single fixed instant. Same parse rules,
    same ValueError."""
    raw = os.environ.get(SNAP_TODAY_ENV, "").strip()
    if raw:
        return _dt.datetime.fromisoformat(raw).replace(tzinfo=_dt.UTC)
    return _dt.datetime.now(_dt.UTC)
