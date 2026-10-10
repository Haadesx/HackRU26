"""Time helpers. All application code reads the clock through utcnow() so tests can freeze it."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_frozen_now: datetime | None = None  # tests only: set via freeze()


def utcnow() -> datetime:
    return _frozen_now if _frozen_now is not None else datetime.now(timezone.utc)


def freeze(at: datetime | None) -> None:
    """Test hook: pin utcnow() to `at` (or unfreeze with None)."""
    global _frozen_now
    _frozen_now = ensure_utc(at) if at is not None else None


def ensure_utc(dt: datetime) -> datetime:
    """Treat naive datetimes as UTC; convert aware ones to UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return ensure_utc(dt).isoformat().replace("+00:00", "Z")


def get_zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def is_valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False
