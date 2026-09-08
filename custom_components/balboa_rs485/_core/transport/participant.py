"""Neutral runtime hook: transport owns arbitration, participant owns command meaning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ..protocol.frames import Frame
from ..protocol.messages import Message

if TYPE_CHECKING:
    from .connection import Snapshot


@dataclass(frozen=True, slots=True)
class Transmission:
    frame: Frame
    token: object


class Participant(Protocol):
    @property
    def recovery_epoch(self) -> int | None: ...

    @property
    def busy(self) -> bool: ...

    def update(self, snapshot: Snapshot, now: float) -> None: ...

    def received(self, message: Message, epoch: int, at: float) -> None: ...

    def prepare(self, now: float) -> Transmission | None: ...

    def sent(self, message: Transmission, at: float, cts_at: float | None) -> None: ...

    def disconnected(self, epoch: int, now: float) -> None: ...
