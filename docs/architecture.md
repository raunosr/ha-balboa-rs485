# Architecture — Phase 0 decision record

Status: researched and reviewed before Phase 1 implementation, 2026-09-05.
Original scope: Phase 0 and Phase 1. Phase 2 decisions and implemented interfaces
are recorded in `phase2_design.md` and `phase2_review.md`. The implemented Phase 3
composition and confirmation policy are in `phase3_design.md`.
Backend repository is `ha-balboa-rs485`;
the existing local directory name need not match the GitHub name.

## Vocabulary and invariants

- A **frame** is a validated length-delimited Balboa wire envelope.
- A **message** is an immutable interpretation of a frame, retaining raw bytes.
- **Observed state** comes only from incoming spa messages.
- **Desired state** is user intent, distinct from physical state and wire commands.
- **READY/CTS** is a bus transmission opportunity, not application availability.
- **Runtime READY** will mean protocol identified, configuration synchronized,
  and fresh physical state available. A TCP connection never establishes this.
- **Connection epoch** will identify one socket lifetime; frame fragments,
  transmission opportunities, and physical transactions cannot cross epochs.

## Module responsibilities

| Layer | Responsibility | Must not own |
| --- | --- | --- |
| Transport | Async sockets, epoch, deadlines, bus scheduling, health | Pump semantics, HA |
| Protocol | CRC, framing, typed decoding/encoding, protocol-specific IDs | Sockets, HA, intent |
| State | Last observed values and capability/configuration snapshot | Optimistic command results |
| Command | Coalesced desired state, next action, confirmation, history | Blind toggle retries |
| Session | Timed heating intent, restoration, persisted intent | Persisted wire commands |
| Prediction | Heating segments, regression, integrated ETA, error metrics | Spa control |
| Energy | Measured deltas / integrated power, interval price accounting | Claiming estimates are measurements |
| HA adapter | ConfigEntry lifecycle, entities, Store, diagnostics, statistics | Protocol parsing |
| Frontend | HA entity discovery, responsive themed views, history | Protocol logic |
| Blueprints | User automation and optional price optimization | Provider coupling in core |

The future runtime composes these layers; imports flow toward the independent
core. The simulator and smoke tool import the same protocol library that the
runtime will use. Runtime dependencies are Python standard library only in Phase 1.

## Phase 1 public interfaces

- `crc8(data) -> int`: checksum over length, address, family, type, payload.
- `Frame(address, family, message_type, payload)`: immutable wire fields;
  `encode_frame(frame) -> bytes` is a pure serializer, never a socket write.
- `FrameParser.feed(chunk) -> list[Frame]`: incremental bounded parser with
  counters and `reset()` for EOF/new connection. Empty feed is not EOF.
- `decode_message(frame)`: `ReadyMessage`, `StatusMessage`, or `UnknownMessage`;
  known IDs with unsupported lengths raise a specific `MessageDecodeError`.
- `Simulator`: async context manager, loopback ephemeral ports supported,
  deterministic fixture stream and four scenarios.
- `observe(...)`: async read-only smoke operation, bounded valid-frame deadline,
  typed output and final counters; no physical-command interface yet.

Tests prioritize independent CRC vectors, all TCP split positions, concatenation,
garbage and delimiter recovery, bad CRC/length/end marker, embedded delimiters,
reset mid-frame, unknown messages, status values, real loopback I/O, EOF, timeout,
cancellation, and zero client TX. These implement the user-approved Phase 1 brief.

## Framing decision

Wire form: `7e LENGTH ADDRESS FAMILY TYPE PAYLOAD CRC 7e`. LENGTH includes itself,
the three header bytes, payload, and CRC, excluding delimiters. Supported LENGTH
is 5..125, matching the conservative Ruby parser bound. Maximum payload is 120.
Do not assume payload cannot contain `7e`; declared length governs parsing.
On invalid length, terminator, or CRC, advance one byte and search again. Keep
incomplete valid-length candidates until enough data or explicit reset. A false
length can delay recovery up to the supported frame bound: do not speculate on
nested delimiters in potentially valid payloads. Persistent residual storage is
bounded by the maximum frame size; input and output batch size remains caller-owned.

CRC uses polynomial 0x07, initial register 0x02, final XOR 0x02, no reflection.
pybalboa's augmented 0xB5 formulation is a confirming implementation; vectors and
an optional local comparison will verify equivalence. Do not copy its source.

## Minimal message decisions

Recognize exact `10 bf 06` with no payload as the classic READY signature.
Other address/CTS combinations stay unknown; recognition alone grants no writes.
Recognize `ff af 13` status with 23..32 payload bytes (Ruby's documented version
range), decoding the common prefix and retaining extension bytes in the frame.
Decode temperatures, units, heat mode/state, range, time, raw pump/light states,
and circulation flag. Avoid capability inference without configuration.
`ff` current temperature means unavailable. Treat `ff` target defensively as
unavailable too (not independently confirmed); preserve the underlying raw byte.
Retain unknown enum values; do not crash or invent a known physical state.
Heating raw value 2 is waiting per pybalboa, not confirmed heater activity.
Do not implement command serialization, faults/config sync, or a SpaState yet.

## Planned transport modes (Phase 2+)

`BwaTcpTransport`, `ClassicRs485Transport`, and `ChannelRs485Transport` should
compose one socket/framing implementation with distinct bus policies. TCP versus
serial URL schemes do not determine safe transmission behavior. Elfin raw TCP
still exposes a shared RS485 bus. Preserve all three header bytes from Phase 1.

Auto-detection starts read-only. Repeated consistent supported traffic and
configuration establish a mode; ambiguous traffic remains UNKNOWN_READ_ONLY.
Classic CTS and assigned-channel CTS can overlap, so a single `10 bf 06` frame
is evidence, not conclusive mode detection. Channel mode needs negotiation,
response correlation, collision handling, and epoch-scoped assignment.

Planned state transitions:
DISCONNECTED -> CONNECTING -> WAITING_FOR_FRAME -> DETECTING_PROTOCOL ->
SYNCHRONIZING -> READY; stale traffic -> DEGRADED -> RECOVERING -> DISCONNECTED.
Use monotonic deadlines for any bytes, valid frames, status, READY, and TX.
Internal policy begins around 3 s degraded, 8 s stale, 12 s hard recovery;
validate thresholds with gateway captures. Keep backoff jitter and clock
injectable. Reset exponential 1..60 s backoff after sustained health.
On reconnect stop writes, cancel transactions, discard raw queues/fragments,
close old socket, resynchronize configuration and observed state, compare
configuration signature, and rebuild capabilities before runtime READY.

The scheduler consumes at most one eligible CTS per physical transmission;
CTS expires promptly and cannot accumulate into future transmission credits.
Do not use arbitrary command sleeps. TCP buffering and Wi-Fi latency may make
bus timing unsuitable even with correct software; hardware measurement is required.

## Desired-state safety (Phase 3)

One in-flight state-changing transaction initially. On a sent toggle with a lost
confirmation, block further physical action until fresh state is observed or
resynchronization completes. A new status identical to the pre-send value is
not necessarily proof of command failure (gateway latency/queued status); Phase 3
must define freshness, settling, and an ambiguity policy. No blind retries.
Compute the next action from current capability-aware observed state and latest
intent. Coalescing replaces intent, never replays a prepared toggle sequence.
Transactions record starting observation, epoch, CTS timestamp, actual TX,
confirmation/timeout, latency, and result in a bounded history.

## Later integration constraints

The HA adapter will own one runtime per ConfigEntry via runtime_data; stop and
unload must await socket tasks and remove callbacks. Connection data includes
host, configurable port, and mode. Preferences hold optional external entities.
Direct RS485 cannot require a Wi-Fi module MAC/iDigi response to configure; stable
device identity needs a separate Phase 4 decision. Rest heat mode is not a physical
power-off guarantee. Fault log data and clear-notification commands are separate.
Store session intent and model state with versions; use recorder/statistics for
history. Predictor never controls the spa. Frontend lives separately in Phase 8.

Phase 5 implements immutable `Session` intent, pure deadline parsing, and an
independent `SessionRunner`. The HA controller only supplies durable Store writes,
wall time, entry lifecycle, and a periodic reconciliation tick. The existing runtime
and command engine retain exclusive control over observed state and transmission.
Session requests carry a synchronous validity predicate evaluated before TX; it
never changes raw protocol messages or bus ownership. See `phase5_design.md` for
expiry, cancellation, endpoint binding and persistence failure policy.

## Pre-implementation review

Boundaries are viable; no HA or runtime command dependency is needed in Phase 1.
The lab deliberately cannot claim reconnection reliability or toggle safety yet.
Golden vectors prevent client/simulator agreement from being the only oracle.
Main unresolved risks: classic versus channel CTS, actual Elfin latency, configuration
requirements/identity, status variations, single-speed pump encoding, and stale
status after TX. Each is an explicit later-phase gate, not hidden in parser code.

## Fixed-address laboratory exception, 2026-09-08

`direct-rs485-tcp-lab` is an explicitly selected, loopback-only direct-transmission
experiment. It does not negotiate channels or claim CTS ownership, and is not a
fallback for any production mode. The observed-state, epoch and command-confirmation
invariants still apply. See `direct_tcp_lab_review.md` for endpoint enforcement,
scope, risk and the separate hardware promotion gate.

Version 0.0.16 separately exposes `direct-rs485-tcp` with explicit core and HA
risk acceptance, never as a fallback. It shares the tested policy without removing
the lab's endpoint boundary. See `direct_tcp_live_review.md`.
