"""Balboa CRC-8: polynomial 0x07, init 0x02, xorout 0x02, unreflected.

Independently implemented from the parameters documented in protocol_sources.md.
"""


def crc8(data: bytes) -> int:
    """Checksum bytes from LENGTH through payload (neither delimiter nor CRC)."""
    register = 0x02
    for octet in data:
        register ^= octet
        for _ in range(8):
            register = ((register << 1) ^ (0x07 if register & 0x80 else 0)) & 0xFF
    return register ^ 0x02
