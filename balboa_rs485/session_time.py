"""Convert an explicit duration or local end time into one UTC deadline."""

from datetime import UTC, datetime, time, timedelta, tzinfo

from .session import _number


def _local_instant(local: datetime) -> datetime:
    wall = local.replace(tzinfo=None)
    instants = {
        candidate.astimezone(UTC)
        for fold in (0, 1)
        if (candidate := local.replace(fold=fold))
        .astimezone(UTC)
        .astimezone(local.tzinfo)
        .replace(tzinfo=None)
        == wall
    }
    if len(instants) != 1:
        raise ValueError("Local end time is ambiguous or nonexistent; specify a UTC offset")
    return instants.pop()


def deadline(
    *, now: datetime, zone: tzinfo, duration: float | None = None, end_time: str | None = None
) -> float:
    if now.tzinfo is None:
        raise ValueError("Current time must be timezone-aware")
    now = now.astimezone(UTC)
    if (duration is None) == (end_time is None):
        raise ValueError("Specify exactly one duration or end time")
    if duration is not None:
        if _number(duration) <= 0:
            raise ValueError("Duration must be positive")
        try:
            return (now + timedelta(seconds=duration)).timestamp()
        except OverflowError as err:
            raise ValueError("Duration is too large") from err
    assert end_time is not None
    if len(end_time) == 5:
        local = now.astimezone(zone)
        end = datetime.combine(local.date(), time.fromisoformat(end_time), zone)
        if end <= local:
            end += timedelta(days=1)
        end = _local_instant(end)
    else:
        end = datetime.fromisoformat(end_time)
    if end.tzinfo is None or end <= now:
        raise ValueError("End datetime must include a UTC offset and be in the future")
    return end.astimezone(UTC).timestamp()
