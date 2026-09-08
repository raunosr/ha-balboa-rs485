"""Internal timing policy, never a fixed sleep used to synchronize bus writes."""

import math
import random
from collections.abc import Callable
from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class Timing:
    connect: float = 12
    first_frame: float = 12
    degrade_after: float = 3
    stale_after: float = 8
    recover_after: float = 12
    sync_timeout: float = 12
    query_timeout: float = 2
    query_attempts: int = 3
    refresh_interval: float = 60
    metadata_refresh_interval: float = 300
    cts_window: float = 0.2
    tick: float = 0.1
    close: float = 2
    backoff_initial: float = 1
    backoff_max: float = 60
    healthy_reset: float = 30

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{field.name} must be finite and positive")
        if not self.degrade_after < self.stale_after < self.recover_after:
            raise ValueError("Require degrade_after < stale_after < recover_after")
        if self.backoff_initial > self.backoff_max:
            raise ValueError("backoff_initial must not exceed backoff_max")
        if type(self.query_attempts) is not int:
            raise ValueError("query_attempts must be an integer")


class Backoff:
    def __init__(self, timing: Timing, *, jitter: Callable[[], float] = random.random) -> None:
        self._timing, self._jitter = timing, jitter
        self._base = timing.backoff_initial

    def next_delay(self) -> float:
        delay = min(self._timing.backoff_max, self._base * (0.8 + 0.4 * self._jitter()))
        self._base = min(self._timing.backoff_max, self._base * 2)
        return delay

    def reset(self) -> None:
        self._base = self._timing.backoff_initial
