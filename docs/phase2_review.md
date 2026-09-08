# Phase 2 review — 2026-09-05

Implemented: eight-state connection lifecycle, supported-mode/configuration/fresh
status gating, typed information/capability responses, configuration fingerprint
and revision, CTS batch freshness/one-send scheduling, bounded query retries,
monotonic health and READY interval statistics, explicit zombie close/reconnect,
epoch reset, jittered exponential backoff and sustained-health reset, bounded
diagnostics, simulator failure scenarios and bounded transport smoke CLI.

Verification: **173 passed, 0 failed; 98.29% combined statement/branch coverage**.
Ruff checks/format and strict mypy passed (21 source files). Real loopback tests
cover first-frame junk, malformed/unsolicited configuration, missing CTS, unknown
and channel traffic, channel veto after sync, reset during a frame, zombie sockets,
signature changes and repeats, bounded retries, cancellation and close failure.
Shutdown availability is revoked before awaiting socket close, protected by a
regression test. No meaningful runtime code is excluded to obtain coverage.

User-authorized 15-second passive hardware check: RX 1,056, TX 0, CRC errors 0,
recoveries 0; addressed channel traffic correctly kept auto UNKNOWN_READ_ONLY.
Water/target decoded as 37 C in a separate passive observer check. See
`hardware_validation.md` for limitations. The real installation is **not yet
write-supported** by this version; do not override the channel veto.

Architecture review: no HA dependencies or pump semantics in socket scheduling;
protocol parsing is pure and raw immutable descriptors are preserved. One owned
connection task and bounded close/backoff paths prevent socket/fragment reuse.
The configuration query API cannot encode physical toggles. Phase 3 must introduce
a separate desired-state engine with explicit transaction cancellation and
ambiguous-confirmation recovery, not expand query retries to physical actions.

Known limits: explicit topology is required for supported query modes; full
channel negotiation is deferred. TCP timestamps do not prove physical CTS window
ownership. Configuration responses have no transaction ID and are not an atomic
pair. Accessory bits disagree upstream and remain raw. No 24-hour soak, hardware
query/control, fault/filter decoding, HA, sessions, prediction, energy or frontend
is claimed. Command-specific and session scenarios remain in their own phases.

Phase 2 is reviewed. The user explicitly authorized proceeding to Phase 3 during
the final checks. Stop after Phase 3 review; no Phase 4 authorization is implied.
