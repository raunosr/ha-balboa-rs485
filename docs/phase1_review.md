# Phase 1 completion and self-review

Reviewed 2026-09-05. Phase 2 is not authorized or started.

## Implemented

Phase 0 documents preceded production code. The implementation contains a Python
3.12+ scaffold with no runtime dependencies; independently written CRC-8 and
incremental framing; immutable validated envelopes; minimal READY, status, and
unknown message types; external factual wire vectors and a packaged synthetic
status fixture; async TCP simulator; receive-only smoke client; four scenarios;
Make targets and a cross-platform dev runner; pytest, coverage, lint, and typing.
No Home Assistant integration is shipped at this phase.

## Verification evidence

Windows, Python 3.12.14; pytest 9.1.1; pytest-asyncio 1.4.0; pytest-cov 7.1.0;
coverage 7.16.0; Ruff 0.16.6; mypy 2.3.1.

- `python -m tools.dev test -q`: **120 passed, 0 failed**, 7.66 seconds.
- Combined statement/branch coverage: **98.97%**, 392 statements and 92 branches.
  Protocol CRC/framing/messages each have **100%** statement/branch coverage.
  No application modules or network error paths are excluded to raise coverage.
  Remaining uncovered paths: accepting a connection during shutdown, and smoke
  writer close timeout/reset fallback. These remain visible in coverage output.
- `python -m tools.dev lint`: Ruff check, format check, strict mypy pass.
- Independent checksum comparison: **5,257 matching vectors** against the pinned
  pybalboa function. The ordinary suite needs no upstream checkout/network.
- `python -m pip install -e '.[dev]'`: successful editable installation.
- Local wheel built; fixture loaded and decoded directly from the wheel archive,
  verifying it is packaged and not accidentally found in the source checkout.
- Actual CLI simulator/smoke session at 127.0.0.1:8899: six received frames,
  zero transmitted frames, zero CRC/length/end errors.

## Example from the actual local smoke run

```text
TCP CONNECTED (read-only; spa availability not established)
CONFIG pending (synchronization belongs to Phase 2)
READY 10 bf 06 observed (classic-rs485 signature; TX disabled)
STATUS Current 27.0 C -> Target 38.0 C; Heat HEATING; Pump1 raw=0
READY 10 bf 06 observed (classic-rs485 signature; TX disabled)
STATUS Current 27.0 C -> Target 38.0 C; Heat HEATING; Pump1 raw=0
READY 10 bf 06 observed (classic-rs485 signature; TX disabled)
STATUS Current 27.0 C -> Target 38.0 C; Heat HEATING; Pump1 raw=0
RX 6 TX 0 CRC errors 0 invalid length 0 invalid end 0 discarded bytes 0 unknown 0 invalid messages 0
```

## Ten-point architecture review

| Check | Finding |
| --- | --- |
| Clean responsibility | Protocol is pure; simulator owns synthetic TX; smoke owns receive/display |
| HA dependency leakage | No HA imports or runtime dependencies |
| Runs against simulator | Four scenarios tested through real loopback sockets; CLI run verified |
| Failure modes tested | Every reference-frame split, corrupt framing, bounded partial/junk waits, EOF, cancellation, malformed/unknown messages, input errors |
| Stale state on connection loss | Smoke retains no live SpaState; fragment reset on exit; freshness/availability state machine deferred |
| Accidental duplicate command | No client command execution exists; explicit zero-TX assertions |
| Reconnect replay | No reconnect or command queue in Phase 1; reset tested; Phase 3 invariant remains unimplemented |
| Diagnostics | Frame counts, CRC/length/end/discard counts, unknown and malformed messages; counters bounded, raw traffic not retained |
| Determinism | Static fixtures, seeded random splits, ephemeral loopback ports, event-driven waits with bounded timeouts; simulator split writes may be coalesced by TCP |
| Assumptions documented | Pinned source matrix, disagreements, supported length/signature limits, every hardware item pending |

## Defects caught during implementation/review

The tests exposed malformed-frame acceptance in the first framing slice, missing
validation/reset behavior, a frame-limit overrun following malformed messages in
one read batch, and invalid CLI durations accepted as success. Each was corrected.
Self-review additionally found a real shutdown-order bug: asyncio.Server.wait_closed
waits for active connections, so waiting before closing client tasks could hang
shutdown. A failing real-socket regression test proved it, then passed after
closing tracked writers/cancelling tasks before waiting for server closure.
Tracking writers separately also protects cancellation before a handler starts.

## Weaknesses and Phase 2 decisions

1. One observed classic READY signature is not sufficient to identify a safe write
   mode. Address ownership/CTS window lifetime and alternate channel traffic need
   a mode policy and captures. Do not turn READY observations into send credits.
2. The parser supports lengths 5..125 and waits for plausible incomplete frames.
   A false length can defer recovery until enough bytes arrive; the observer's
   whole-frame deadline prevents indefinite waiting. Wider envelopes require tests.
3. Configuration/model/fault/filter messages are research only. Direct RS485 must
   not require a Wi-Fi module identity response. HA device identity and configuration
   signature changes require explicit design before adding entities.
4. Preserve raw pump/light values until capability mapping is implemented. A
   single-speed pump may report 2; heat waiting is distinct from active heating.
5. The simulator models stream faults, not electrical bus arbitration, Elfin Wi-Fi
   latency, configuration requests, or command effects. Phase 2 must add these
   relevant scenarios before using it as a transport reliability oracle.
6. Phase 3 must prove the lost-status-after-toggle invariant. Freshness after TX
   needs more than receiving any status packet; gateway buffering can deliver old
   observations. Do not claim this invariant is already proven by zero-TX tests.
7. Keep future socket lifecycle/deadline policy in the transport layer. Phase 1's
   short observer lifecycle is a lab tool, not the future runtime state machine.

## Hardware validation pending

All real Elfin/spa behavior: connection/configuration, CRC/status decoding against
the panel, READY addresses and timing, shared-bus TX safety, pump capabilities,
setpoint and toggle confirmation, reconnect/zombie recovery, firmware variants,
24-hour and 72-hour soaks. No real hardware was contacted or controlled.

## Release boundary

GitHub is private under `raunosr`; repository publication does not make this a
V0.1 release. No HA entities, command engine, heating sessions, ML, energy,
frontend, or blueprints were implemented. The independent frontend repository
belongs to Phase 8. Await user review before Phase 2.
