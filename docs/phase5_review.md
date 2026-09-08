# Phase 5 review — complete, simulator validated

Later production-installation and user-authorization updates are recorded in
`hardware_validation.md` and `implementation_plan.md`. The boundaries below
describe the original laboratory review, not the current approval state.

Reviewed 2026-09-06. Version **0.0.5**, targeting **Home Assistant 2026.8.3+**
and tested on exactly 2026.8.3. Phase 5 is complete. **Stop before Phase 6**;
prediction, hardware testing, HA installation/restart and publication need
separate approval.

## Delivered

- Independent immutable session intent, deadline parsing and session runner;
  no Home Assistant dependency in the Python core.
- Start by duration or end time; extend/reduce by 30 minutes by default; cancel
  to maintenance. Explicit units and observed range/step validation. DST gaps
  and ambiguous local times are rejected. Expired sessions cannot be resurrected.
- Atomic/private HA Store intent saved before commands and checked with a fresh
  readback. Entry connection binding, corrupt/unreadable/failed/interrupted storage
  protection, restart reconciliation, unload preservation and entry-only deletion.
- Observed preheating/target-reached/holding/restoring phases and a native bilingual
  sensor. Manual HA setpoints abandon sessions; physical-panel changes are reported
  rather than repeatedly overwritten.
- Pre-transmission admission guards prevent expired, disabled, closed or old-epoch
  session goals from being sent between scheduler ticks. In-flight confirmation
  and resynchronization guards remain owned by the existing command engine.
- Self-contained HACS-compatible ZIP with the existing original local icon,
  action selectors and English/Finnish strings. No private pip dependency.

## Evidence

Green code/test candidate **0ccf751**:
[CI 34028249668](https://github.com/raunosr/ha-balboa-rs485/actions/runs/34028249668).

| Check | Result |
| --- | --- |
| Core/tools, Python 3.12 | 328 passed; 97.47% branch-aware coverage |
| Actual HA 2026.8.3, Python 3.14.7 | 48 passed; 97.19% adapter coverage |
| HA session controller/actions/sensors | 100% statements and branches |
| Extracted ZIP in a separate HA process | 1 passed; installed session lifecycle and original icon HTTP bytes verified |
| Ruff lint/format, canonical strict mypy | Passed; 36 typed source files |
| Adapter/bundled core strict mypy | Passed; 35 typed source files |
| Generated core equality and reproducible packaging | Passed |

Windows also passed all 328 core tests, lint and strict typing. Both existing
95% coverage gates remain unchanged. The generated HA core copy is measured in
the canonical suite, not double-counted in adapter coverage.

Tests use real TCP and HA lifecycle APIs. Clock/persistence fault boundaries are
substituted; HA's test storage fixture serializes JSON in memory. These are not
power-loss durability tests or physical-spa validation. The final deletion-test
failure was a test-fixture cached Store instance; a fresh owner correctly sees
the removed record. No production change was needed for that test correction.

## Artifact and boundaries

`dist/ha-balboa-rs485-0.0.5.zip`: **1,229,610 bytes**.
SHA-256: `f6a3dfe040b1338be992492538a7449ae526c709e48c904e62748f65c6823deb`.
The previous 0.0.4 ZIP is preserved. Installation and actions are documented in
`home_assistant.md` and `heating_sessions.md`.

The timer runs in HA, not in the spa controller. Offline/disabled restoration
waits for enabled controls and fresh safe observations. Cancel and confirm
maintenance before shutting down HA or removing/reconfiguring an active entry
if the physical setpoint must not remain high. Storage errors cannot undo an
already sent command. Heating readiness by a deadline is not predicted.

No physical spa connection, HA installation/restart, public release, default-branch
merge or license/publication decision was made. The repository remains private on
`codex/phase5-heating-sessions`; HACS-compatible does not mean publicly HACS-listed.
Hardware negotiation, firmware behavior and RS485 timing remain unvalidated.
