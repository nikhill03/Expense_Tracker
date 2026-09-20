"""The app's idea of what day it is.

An expense date is what a person would write in a ledger, so it has to follow the
*user's* calendar day, not the server's. Railway runs in UTC; India is UTC+5:30.
Without this module, every expense logged between midnight and 5:30am IST is
dated to the previous day — which is exactly the late-night debit-alert case the
quick-add screen exists for.

Set APP_TIMEZONE to move the app somewhere else. Everything user-facing —
"today", the month a budget belongs to, the dashboard's date presets — goes
through here.

Deliberately a top-level module rather than a helper in app.py: database/queries
needs it too, and app.py already imports from database.queries, so putting it
there would make the import circular.
"""

import logging
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Asia/Kolkata"

# India has never observed DST, so a fixed +05:30 is exact. It is the last
# resort for an image that ships no tz database at all — requirements.txt pins
# tzdata so that should not happen, but degrading beats refusing to start.
_FIXED_IST = timezone(timedelta(hours=5, minutes=30), "IST")


def app_timezone() -> ZoneInfo:
    """The configured zone, falling back to IST.

    A typo in APP_TIMEZONE should not take the app down, so an unknown name
    falls back rather than raising on every request.
    """
    name = os.environ.get("APP_TIMEZONE") or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        pass

    logging.getLogger(__name__).error(
        "APP_TIMEZONE=%r could not be resolved; falling back to IST", name
    )
    try:
        return ZoneInfo(DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        # No tz database on this image at all.
        return _FIXED_IST


def now() -> datetime:
    """The current time where the user is, timezone-aware."""
    return datetime.now(app_timezone())


def today() -> date:
    """The user's current calendar day."""
    return now().date()
