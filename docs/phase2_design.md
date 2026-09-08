# Phase 2 transport design

Approved by the user on 2026-09-05. Phase 1 remains the passive observation tool;
Phase 2 adds a standalone connection runtime, not HA or physical controls.

## Safety decision: mode selection

An assigned channel can produce the same `10 bf 06` and `ff af 13` traffic as
classic RS485. No finite number of those frames proves classic operation.
Therefore **auto is passive UNKNOWN_READ_ONLY**, with a classic-compatible or
channel candidate reported as evidence, never permission. Explicit classic or
BWA selection is an operator assertion about the topology. Channel traffic
vetoes writes for the rest of that socket epoch even with an explicit mode.
Channel negotiation is intentionally unsupported in this phase. BWA selection
must never be used as a workaround for missing CTS on an Elfin raw bridge.

`BwaTcpTransport`, `ClassicRs485Transport`, and `ChannelRs485Transport` are small
bus strategies composed by `SpaConnection`, which owns the single socket. The
classic strategy consumes only the final complete READY in a received batch,
with no trailing partial frame, within a short monotonic freshness window.
Multiple buffered CTS frames are not credits. Actual RS485 timing cannot be
proved from TCP arrival timestamps; hardware capture/latency validation remains
required before controls. BWA does not need CTS; channel and auto never transmit.

## Slices and public behavior

1. Pure typed system information (BF24, exactly 21 bytes), raw capabilities
   (BF2E, exactly 6 bytes), and versioned configuration signature. Preserve raw
   accessory descriptors because source bit tables disagree.
2. Read-only query enum (BF22 information `02 00 00`, capabilities `00 00 01`),
   bus strategies/detection, and bounded exponential backoff. No arbitrary-frame
   sending API and no BF11/BF20 encoder or physical transaction queue.
3. Async connection context: one owned runner, bounded connect/first-valid-frame,
   configuration and status gates, monotonic health, deterministic cleanup,
   reconnect epochs, config refresh/revision, and bounded event diagnostics.
4. Real loopback failure scenarios and transport smoke CLI, preserving Phase 1
   receive-only defaults. Tests progress red -> green in small behavior slices.

Required states: DISCONNECTED, CONNECTING, WAITING_FOR_FRAME,
DETECTING_PROTOCOL, SYNCHRONIZING, READY, DEGRADED, RECOVERING. READY requires
an explicit supported mode, correlated information and capability responses in
the current epoch, and a fresh status after synchronization started.

Defaults: degrade after 3 s, stale after 8 s, hard recovery after 12 s; first valid
frame within 12 s. Missing status, valid traffic, or classic CTS inhibits queries
when degraded. Hard deadlines close zombie sockets even if junk or unrelated
valid traffic continues. Unknown auto/channel traffic remains passive but is
still monitored for silence. Configuration queries are the only retryable
transactions; each has a response deadline and bounded attempts. A partial
refresh never replaces a committed configuration; reconnect clears current
configuration/status and compares the next complete signature to the last one.

Recovery clears parser fragments and query state, closes/awaits the old writer,
then waits exponential 1..60 s backoff with bounded jitter. Reset backoff only
after sustained READY health. No socket, CTS opportunity, query response, or
prepared bytes can cross epochs. Phase 3 will implement the separate physical
transaction cancellation and no-toggle-replay contract; it is not proven here.

## Hardware coordination

The user supplied an Elfin endpoint on the private LAN (port 8899). BWAlink used it.
Do not connect until the user confirms BWAlink is stopped. Begin with bounded
passive observation; do not infer write-safe mode from the IP address or an open
TCP socket. Hardware validation is separate from reproducible loopback tests.
