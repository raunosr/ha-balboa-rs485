# Controlled implementation plan

Phase 0 research and architecture precede production code. Phase 1 follows in
small test/implementation cycles; run the relevant test for each behavior and
the complete suite at completion. Phases 1, 2, 3, 4 and 5 are reviewed. Phase 4 includes
the channel prerequisite, HACS-compatible packaging and an original icon.
Phase 5 laboratory validation is complete. On 2026-09-06 the user authorized
autonomous continuation through Phase 11 after the Phase 5 production
installation/hardware acceptance tests pass. The short target/session acceptance
gate passed on 2026-09-07 with installed 0.0.9. Phase 6 completed with installed
0.0.11, 455 passing automated tests and bounded production/UI acceptance; see
`docs/phase6_review.md`. Phase 4B is next, before Phase 7.
On 2026-09-08 HACS-managed 0.0.14 was activated and the native pump sequence passed.
Filter restoration exposed a confirmation failure; the 0.0.15 candidate and its
remaining hardware gate are recorded in `docs/filter_confirmation_review.md`.
The subsequent installed 0.0.15 filter retest passed, but Low-to-High bathing and
channel recovery failed. See `docs/bwalink_transport_review.md` for the current
transport research and rejected rolling-allocation experiment. Do not advance to
Phase 7 or migrate automations before these remaining gates are reviewed.
The user subsequently authorized a loopback-only fixed-address direct RS485/TCP
experiment. Its implementation, naming and validation are recorded in
`docs/direct_tcp_lab_review.md`. This does not promote the mode to production.
The later owner-authorized 0.0.16 live promotion/trial is recorded separately in
`docs/direct_tcp_live_review.md`; short compatibility tests do not close Phase 11.
The 2026-09-07 MQTT inventory and revised dual-range/session UX are recorded in
`docs/phase4b_design.md`. The complete 0.0.14 native-entity implementation includes
range-aware restoration, filters and guarded maintenance controls. Production
acceptance, HA startup recovery and unresolved Cycle 1/long-soak gates are tracked in
`docs/phase4b_review.md`; see `docs/native_controls_0_0_13.md` for current behavior.
On 2026-09-07 installed 0.0.8 demonstrated automatic channel-ACK recovery on real
hardware. Installed 0.0.9 (415 automated tests) then passed physical target change,
restoration and timed maintenance including integration reload with the original
deadline retained. Long-duration channel-budget recovery remains an explicit
final-acceptance limitation, not a passed soak.
See `docs/bp6013_compatibility_review.md` for the exact installation/restart boundary.

| Phase | Deliverable and exit gate |
| --- | --- |
| 0 | Pinned source/license review, architecture, source matrix, local test and hardware plans; self-review before code |
| 1 (complete) | Scaffold, CRC, incremental parser, minimal typed READY/status/unknown messages, fixtures, async simulator (normal/bad-crc/partial-frame/garbage-before-frame), read-only smoke client, pytest/coverage/lint/dev commands, self-review |
| 2 (complete) | Three mode policies, first-frame gating, connection state machine, CTS scheduler, zombie recovery/backoff, configuration sync/signature, transport failure scenarios; passive channel fallback |
| 3 (complete) | Observed SpaState, desired-state engine, verified commands/coalescing/history, mandatory dropped-confirmation toggle tests |
| 4 (complete) | Channel-transport prerequisite; native HA config/options/runtime/entities, unload/reload/diagnostics, simulator-based HA tests, HACS packaging and local brand icon |
| 5 (complete) | Heating sessions/actions/Store, expiry and restart intent restoration |
| 6 (complete) | Heating windows, lightweight online regression, persistence, integrated ETA, held-out thermal simulation evaluation; five native sensors and actual HA options/UI acceptance |
| 4B (after 6, before 7) | Complete the supported native sensor/control/diagnostic gaps in entity_parity.md; individually verify semantics, simulator tests and safe hardware acceptance. Phase 4's completed adapter foundation did not mean full MQTT parity |
| 7 | Optional measured energy/power and provider-neutral prices, interval costs/statistics |
| 8 | Separate `balboa-spa-card` repository, simple/auto card, device discovery, theme/grid/demo fixtures |
| 9 | Detailed controls, sessions, prediction, responsive charts and energy periods |
| 10 | Automation blueprints and tests/docs |
| 11 | Read-only hardware soak, controlled writes, failure tests, 72-hour soak |

Every phase ends with a review. The 2026-09-06 approval permits continuation through
the remaining planned phases, subject to the acceptance gate and production safety
constraints in AGENTS.md. V0.1 is the combined later product, not the Phase 1 laboratory.

## Phase 1 slices

1. Independent checksum vectors -> minimal CRC implementation.
2. Valid frame round trip -> immutable envelope/serializer/parser.
3. TCP split/garbage/bad-envelope/reset cases -> recovery and diagnostics.
4. READY/status fixtures -> minimal typed decoding and unknown preservation.
5. Real loopback stream -> async simulator and observer using the same core.
6. Four network scenarios -> recovery, bounded timeout/EOF/cancellation tests.
7. CLI and cross-platform dev runner -> test, lint, simulator, smoke, lab.
8. Full pytest with branch coverage, Ruff, strict typing, actual CLI session,
   packaging validation, and documented review. Backend target >95% coverage;
   do not exclude meaningful network/error code just to meet the number.

## Scope resolution

The master brief's eventual interactive `pump1 high` smoke workflow needs the
Phase 3 command engine. Phase 1 smoke is receive-only and explicitly reports
configuration as pending. A pure frame encoder serves simulator fixtures, not
hardware controls. Four scenarios shipped in Phase 1; Phases 2/3 add transport
and command scenarios (thermal/session scenarios belong to their later phases).
No frontend, blueprint, predictor, or energy implementation in Phase 4.

## Review checklist

Before final replacement acceptance, close or explicitly document the supported
native entity gaps in `entity_parity.md` (the user's 2026-09-06 MQTT screenshot).
Successful channel negotiation alone does not complete these HA mappings.

Check layer ownership, absence of HA imports, simulator usability, failure cases,
stale state, duplicate execution, reconnect replay, sufficient bounded diagnostics,
determinism, and source-documented assumptions. Record actual results in
each phase's review document. Completed reviews: `docs/phase1_review.md`,
`docs/phase2_review.md`, `docs/phase3_review.md`, `docs/phase4_review.md`,
`docs/phase5_review.md`, and `docs/phase6_review.md`.
