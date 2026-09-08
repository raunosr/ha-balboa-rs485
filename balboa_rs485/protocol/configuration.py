"""Read-only configuration protocol, independent of network lifecycle."""

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256

from .frames import Frame
from .messages import CapabilitiesMessage, SystemInformationMessage


class Query(Enum):
    INFORMATION = b"\x02\x00\x00"
    CAPABILITIES = b"\x00\x00\x01"
    SETUP = b"\x04\x00\x00"
    FILTERS = b"\x01\x00\x00"
    FAULT = b"\x20\xff\x00"


def encode_query(query: Query) -> Frame:
    """No raw or state-changing command interface is exposed in Phase 2."""
    if not isinstance(query, Query):
        raise ValueError("Only supported configuration queries may be sent")
    return Frame(0x0A, 0xBF, 0x22, query.value)


@dataclass(frozen=True, slots=True)
class Configuration:
    information: SystemInformationMessage
    capabilities: CapabilitiesMessage

    @property
    def signature(self) -> str:
        """Versioned fingerprint includes all raw fields, not merely model name."""
        data = self.information.frame.payload + self.capabilities.frame.payload
        return "v1:" + sha256(b"balboa-config-v1\0" + data).hexdigest()
