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

Hardware acceptance is pending. A successful download is not a successful command,
and a short successful command is not long-duration weak-link acceptance.
