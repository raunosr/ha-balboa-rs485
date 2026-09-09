# Direct RS485/TCP fixed-address compatibility trial

## Promotion review — 2026-09-09

The owner explicitly authorized preparing and testing a live fixed-address mode.
The panel remains a bus participant. Two known users do not establish collision-free
arbitration. This is an opt-in compatibility experiment, not a negotiated-channel
fix or a claim that this mode is universally safe.

Version 0.0.16 adds `direct-rs485-tcp` separately from the loopback-only lab mode.
Existing entries/defaults are unchanged. The core requires an explicit
`allow_unarbitrated_writes=True`; HA requires `accept_direct_bus_risk` in its
official setup/reconfigure form before even validating the connection. This
includes configuration queries, which remain active when physical controls are
disabled. Form validation itself is passive and reuses fresh owned observations.
Changing back to another mode clears acceptance. Do not bypass the lab guard.

The common tested policy uses source 0x0A, no allocation and no CTS claim. One
complete receive batch permits at most one transmission per 100 ms; this is an
anti-burst policy, not a bus timing guarantee. Unknown families, observed competing
fixed-address writes/echo, stale state, locks and ambiguous confirmations retain
their guards. A conflict inhibits writes for the epoch; there is no promise of
automatic recovery while a competing writer remains active.

Socket EOF/silence recovery retains deadlines, backoff, parser reset, a single
owned connection and fresh configuration/state in each epoch. Desired-state
reconciliation is not replay of an old raw toggle. Diagnostics expose the requested
mode and unarbitrated flag even when effective mode is read-only.

## Test and rollback plan

1. Required core/actual-HA/isolated-ZIP tests, lint, types and bundle equality.
2. Reviewed PR and versioned HACS download; preserve the entry/device/entity IDs.
3. Verify the other network client is stopped, controls disabled and no session
   intent pending. Capture original values from fresh state, not old screenshots.
4. Activate the HACS version with an authorized HA Core restart. No spa restart.
5. Reconfigure the existing entry with explicit risk acceptance. First verify
   fresh status, READY and metadata without physical commands.
6. One reversible control change and independent observed readback, then restore
   the fresh original. Stop on ambiguity; never blindly resend toggles.
7. Only after that gate passes, review the previously failed range/session gate.
   Network failure injection stays in the lab, not the production HA.

Rollback: disable physical controls and use official reconfigure to `auto`
(passive). If package rollback is required, use HACS to download v0.0.15 and obtain
or use a remaining authorized Core restart. Keep all registry/storage objects.
No automation migration, Core/OS upgrades or unrelated integration changes.

## Evidence

The earlier lab-only branch passed 566 core/tools tests, 85 actual-HA tests and
one isolated-ZIP test. These are prior results, not results for the live promotion.
The promotion's shared-policy focused suite passed 37 tests in 15.70 seconds,
including live opt-in rejection, >3 disconnects with zero allocations, silent
socket recovery and lost-confirmation handling for both explicit mode IDs.
Full promotion CI and physical outcomes must be recorded separately below.

First full promotion run passed 585 local core/tools tests (97.09% coverage).
Actual-HA CI caught an unintended reconnect on a no-op legacy reconfigure: adding
the new false acceptance key changed entry data and triggered the update listener.
The existing one-socket regression test reproduced it (87 other tests passed).
Non-direct legacy entries now omit that irrelevant key, while leaving direct mode
explicitly clears prior acceptance. This correction requires a fresh HA CI pass.

Hardware acceptance was pending at publication. The subsequent bounded result is
recorded below; it is not long-duration weak-link acceptance.

## Bounded hardware result — 2026-09-09

The corrected PR passed **585 core/tools tests**, **88 actual-HA tests** and
**one isolated-ZIP test** (674 total), plus HACS, lint, strict typing and bundle
checks. Core coverage was 97.09%; adapter coverage 97.20%. Released as v0.0.16
after normal protected-branch review; no protection bypass or automatic merge.

HACS installed v0.0.16. One authorized Core restart activated it; the version was
verified in both the UI and diagnostics. The other network client was freshly
confirmed stopped. Official reconfigure preserved the device and all 54 entity
IDs, and the new mode reached READY with complete BP6013G2 metadata and no channel
allocations. Physical controls stayed disabled until those checks passed.

| Bounded control intent | Independently observed outcome |
| --- | --- |
| Light on | First transaction timed out after 4.01s; automatic new connection and fresh-state reconciliation reached VERIFIED, light on |
| Restore light off | Same recovery path; VERIFIED and original off state restored |
| High to Low | VERIFIED in 0.402s, observed Low and its stored target |
| Restore High | VERIFIED in 0.443s, original High setpoint restored |

These were **four HA service requests**, six physical transactions: four verified
and two initially ambiguous. No extra service request, manual reload or restart
was used to recover the lights. Each recovery closed the old socket, resynchronized
and derived the next action from fresh unchanged light state. The successful
post-recovery transaction latencies were 0.204s/0.294s; those do not include the
earlier timeout/backoff and must not be advertised as total response times.

Final command checks: READY in epoch 3, two recoveries, zero channel allocations,
zero CRC errors, no invalid decoded messages, complete metadata, original High
setpoint/light state and both filter schedules intact. No bathing-session intent
was created and no automation was changed. The controller's own circulation
behavior was observed, not forced back to an earlier pump snapshot.

This passes the bounded direct-mode light/range compatibility test and demonstrates
two real automatic recoveries. It **does not prove first-attempt reliability,
collision-free operation, all advanced-control acceptance, bathing-session
Low-to-High/end restoration in this mode, or a long-duration network soak**.
The experimental label remains appropriate. No second restart was needed.
