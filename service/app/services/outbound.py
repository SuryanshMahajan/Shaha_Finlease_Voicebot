"""Pure outbound workflow eligibility helpers; never initiate a call."""
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo


def utc_now() -> datetime:
    """Clock seam for deterministic policy and route tests."""
    return datetime.now(timezone.utc)


def calling_window_open(now: datetime, timezone_name: str, start_hour: int, end_hour: int) -> bool:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Current time must be timezone-aware.")
    if not 0 <= start_hour < end_hour <= 24:
        raise ValueError("Calling hours must be a valid increasing local-time window.")
    local_time = now.astimezone(ZoneInfo(timezone_name)).time().replace(tzinfo=None)
    start = time(start_hour, 0, 0)
    # A configured end hour of 24 means the final representable time of day.
    end = time(23, 59, 59, 999999) if end_hour == 24 else time(end_hour, 0, 0)
    return start <= local_time <= end
