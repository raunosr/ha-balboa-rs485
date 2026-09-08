# Channel ACK resilience — 0.0.7 / 0.0.8

## Current finding: 0.0.7 did not solve this controller; 0.0.8 follow-up

Restart 1/2 completed: HA 2026.8.3 RUNNING at 07:54:12 UTC. BWALink was stopped
before enabling Balboa. Installed 0.0.7 failed its first handshake. One further
authorized integration-only reload reproduced the failure and captured the
actual rejecting pattern in a 25-second EW11-only capture:

- Valid correlated channel **22** response after **62.175 ms**.
- Response first of **three frames in one TCP packet**, followed by `11 BF06`
  and `11 BF07`. No partial tail or previously observed client on channel 22.
- No channel-22 CTS after the request. Channels 16..21 each received 105 or 106
  CTS frames in the capture; the offered channel received zero.
- No ACK or physical command sent. HA stayed DETECTING_PROTOCOL.

This confirms coalescing closes the immediate ACK slot, not a late two-second
response or an occupied/invalid address. It falsifies deferred CTS as a solution
on this controller. The conservative 0.0.7 path remains inert here; it does not
justify sending a late ACK on another client's slot.

0.0.8 fixes the remaining permanent first-attempt stall: close the failed socket,
apply existing bounded backoff, and negotiate in a new epoch on a fresh invitation.
The nonce differs even if the random generator repeats. Old replies cannot ACK
the new request. The maximum of **three allocation requests per runtime** remains;
after the final failure stay read-only rather than resetting the budget or looping.
No late TX, physical-command replay, or public publication is introduced. Persistent
severe buffering can still exhaust the safety limit; arbitrary latency is not safe.

A real-TCP regression using the captured three-frame pattern failed before the fix
and now reaches READY in epoch 2 with one ACK total, rejecting an injected old-nonce
reply. Last-budget and connection-loss-budget tests still pass. Local 342 tests
passed, 97.54% coverage, plus lint/format/typing/bundle checks. Private CI
[34098821512](https://github.com/raunosr/ha-balboa-rs485/actions/runs/34098821512)
passed both core and actual-HA jobs on `f16a4858f80cd1ffe9dd5b950fe73dcf7a15d42a`:
342 core tests (97.54%), 50 actual HA tests (97.19%), one separate ZIP installation
test; 393 passing tests total. Formatting, lint and both typing jobs also passed.

0.0.8 was installed after Balboa-only unload, with all 41 files byte-verified.
Archive SHA-256: `4c86cff67b94a92d3edb093d1643e7a523395c990ec6d075d310803dccc4f1d3`.
Previous 0.0.7 is retained at
`/homeassistant/.balboa-backups/0.0.7-m3u9ix1_/balboa_rs485`.
The transfer endpoint closed after delivery. Restart **2/2** was requested and
accepted at **2026-09-07 08:15:17 UTC**. HA 2026.8.3 RUNNING was verified at
08:19:33 UTC. BWALink was verified stopped before enabling Balboa once.

**Installed 0.0.8 recovered automatically and reached READY in epoch 3**, channel
22, after two failed allocations: attempts 3/3, recoveries 2, one eligible ACK
opportunity on the successful epoch. Configuration synchronized; observed water
and target both 37 C, heater OFF. This is hardware evidence for bounded recovery,
not a guarantee against arbitrary future packet buffering or a 72-hour soak.

The subsequent HA target test failed before transmission: `Controls require a
fresh synchronized normal operating state`. Command history remained empty and
the observed setpoint remained 37 C. Supplemental SETUP decoding also failed.
These are separate protocol-variant acceptance issues, now recorded in
`bp6013_compatibility_review.md`. Controls were disabled again through options,
without reconnecting. No physical spa command was transmitted. Phase 6 still
awaits successful physical-command/session acceptance.
**Correction restarts used: 2/2; no further Core restart for this correction.
Physical spa commands transmitted: none. Phase 6: not started.**

The user subsequently authorized two separate Core restarts for Phase 6, only
after the channel correction works and hardware acceptance permits Phase 6.
Phase-6 restart budget: **0/2 used**, not applicable to unresolved Phase-5 faults.

The remainder records the previous 0.0.7 checkpoint for auditability.

## Evidence and limits (2026-09-07)

HA 0.0.6 had a correlated assignment response but no eligible immediate ACK slot,
then stayed DETECTING_PROTOCOL. Its aggregate counters do not identify which
individual timing/address guard rejected that historical response.

Two explicitly authorized integration-only reloads subsequently reached READY
without a code change (channels 20 and 21). A bounded, EW11-only passive capture
of the latter showed a valid, previously unoccupied channel 21, matching nonce,
response after 76.822 ms in a single-frame packet without residual data, and ACK
13.694 ms later. Configuration synchronized. This proves intermittent success,
not that the old failure disappeared or that any new code fixed production.
Some CRC and metadata decode errors were observed after synchronization; they
remain a separate hardware acceptance observation, not attributed to Wi-Fi alone.

The first capture command failed before capture (BusyBox mktemp template syntax);
the corrected capture recorded 2,000 packets with zero kernel drops. Raw capture
and temporary analysis code are private/ignored, not repository artifacts.

## Change and safety review

The old implementation discarded a correlated offer if its immediate reply slot
was already followed by more traffic. It could not ACK even if the controller
subsequently offered a fresh CTS on the explicitly assigned address. Two real-TCP
regressions reproduced this failure before implementation: batched and partial
tails. They now reach synchronized READY using exactly one request and one ACK.

The new candidate is correlation state, **not channel ownership or a saved TX
credit**. An ACK can use the immediate assignment slot as before, or a new,
complete, terminal CTS on the candidate address within the original two-second
request deadline. It cannot use another address, a partial/batched-away CTS,
conflicting assignment, previously observed client address, expired request, or
previous socket epoch. ACK is sent once; a later owned CTS and configuration plus
fresh status are still required for availability. Allocation and physical-command
budgets are unchanged. No arbitrary delayed TX or blind toggle replay is added.

The [protocol reference](https://github.com/ccutrer/balboa_worldwide_app/wiki#clear-to-send)
defines addressed CTS as permission for that client to send a message. It also
says some controllers start polling only after ACK. Accordingly, the deferred
path is a conservative recovery opportunity, **not a compatibility guarantee**:
if no candidate CTS arrives, the handshake still times out safely. The precise
historical HA rejection remains unproven until a failing attempt is captured.

Diagnostics add `pending` and `ack_on_cts`, without exposing correlation bytes.
The latter records an actually sent ACK, not an optimistic ownership claim.

## Delivery state

Private CI [34096864766](https://github.com/raunosr/ha-balboa-rs485/actions/runs/34096864766)
passed on `bff2fbc975247e9c82c1daf3e054f79fd950fd9c`: 341 core tests
(97.53% coverage), 50 actual HA 2026.8.3 tests (97.19%), one separate ZIP install
test, lint, formatting, strict core/adapter typing and bundle equality. Total 392
passing tests. The local core run also passed all 341 (97.59% coverage). Its first
attempt hit five Windows temporary-directory permission errors; using a fresh
workspace-local test directory resolved them without changing tested code.

0.0.7 was installed on production on 2026-09-07 after Balboa-only unload. All 41
files matched the reviewed archive, SHA-256
`1107cb57a5a3a0e6a0fef4ea434f53d786996df8c799da38fdd3b9f9ab4d6730`.
The old 0.0.6 directory remains under `/config/.balboa-backups/`; no other
integration, registry, configuration or Core/OS version was changed. The
single-artifact HA-IP-allowlisted transfer endpoint closed after delivery.
Production 0.0.7 hardware acceptance is still pending at this checkpoint.

The current user authorization permits Balboa-only unload/reload as needed and
at most **two agent-initiated HA Core restarts** before asking again. Zero have
been used before installation; **restart 1/2 was requested successfully at
2026-09-07 07:49:41 UTC** to load 0.0.7. Do not repeat an uncertain restart.
Another integration's
agent may restart HA independently; do not modify its files or assume exclusive
ownership of production uptime. Phase 6 remains gated on hardware acceptance.
