# Phase 4 review — complete, simulator validated

Reviewed 2026-09-05. Version **0.0.4**, experimental custom integration targeting
**Home Assistant 2026.9.0+**. Phase 4 includes the channel prerequisite, native HA
basics, HACS-compatible structure and an original icon. **Stop: Phase 5 is not
authorized.** No real-spa control readiness is claimed.

## Implemented

- Correlated channel assignment, addressed queries/commands, owned CTS,
  collision/echo veto, one request per socket and three per runtime. Tests reject
  wrong nonces, no-CTS channels and trailing garbage without sending ACK/query.
- One independent runtime per ConfigEntry. No HA imports leak into the core;
  generated `_core` is byte-checked against the canonical source.
- Passive validation, duplicate/concurrent-flow prevention, stable entry-scoped
  identity and endpoint reconfiguration without competing validation connections.
- Observed climate, single-/two-speed pumps, blower, on/off lights, supported
  aux/mister switches and a diagnostic connection sensor. Capabilities can appear
  or become unavailable without losing registry identity. No fake HVAC OFF,
  brightness or optimistic physical state.
- Explicit control opt-in; observation-verified actions. Disabling controls,
  cancelling a caller or unloading cancels remaining intent without undoing or
  replaying an already transmitted physical step.
- Awaited unload/reload/shutdown and failed-setup cleanup. No-status channel
  startup retains its runtime/budget instead of triggering fresh HA setup retries.
- Allowlisted/redacted JSON diagnostics and bounded transaction history;
  English/Finnish configuration, options and entity metadata.
- HACS metadata, self-contained reproducible ZIP builder and original RGBA icon
  served locally by HA. No private pip dependency, MQTT, Docker, add-on or cloud.

## Validation evidence

Passing Linux candidate [32b3c50, CI 33990531055](https://github.com/raunosr/ha-balboa-rs485/actions/runs/33990531055):

| Check | Result |
| --- | --- |
| Independent core/tools, Python 3.12 | 265 passed; 97.17% branch-aware coverage |
| Real HA 2026.9.0, Python 3.14.7 | 33 passed; 96.87% adapter branch-aware coverage |
| HA configuration flow | 100% statements and branches |
| Extracted ZIP in a fresh HA process | 1 passed; bundled core loaded and authenticated local icon bytes matched |
| Ruff lint/format | Passed |
| Strict mypy, canonical core/tools | Passed, 33 source files |
| Strict mypy, adapter/bundled core | Passed, 30 source files; installed HA types, dependencies followed silently |

Windows also passed the complete core suite: 265 tests, 97.17%. A subsequent
packaging regression exposed platform-dependent ZIP creator metadata; the builder
now pins UNIX creator/permission metadata on Windows too. Its six packaging tests
pass locally. Identical input bytes produce repeatable archives in the tested
environment; different source line endings or compression-library versions are
not a cross-platform byte-identity guarantee.

The separate HA 95% gate omits only generated `_core`, because canonical core/tools
have their own gate and the pipeline enforces bundle equality. No adapter/error
code is excluded to inflate coverage.

Tests exercise real HA flows, entities, services, registries and lifecycle over
real TCP streams. They cover dropped confirmation without toggle replay,
non-optimistic state, unavailable-but-open sockets, changing capabilities,
single-socket ownership, cancellation, shutdown and diagnostic privacy.
The installation HTTP test ignores only aiohttp's `NotAppKeyWarning` from HA's
deliberate `app["hass"]` compatibility shim, not integration errors.
Exact commands are in `local_testing.md`; installation in `home_assistant.md`.

## Artifact

Local archive: `dist/ha-balboa-rs485-0.0.4.zip` (1,218,911 bytes).
SHA-256: `332af4ea0191645d76a759d7a7b0b366bd31eb6ef81628fbfd75df22b55dc1aa`.
Extract under the HA configuration directory, preserving the included
`custom_components/balboa_rs485/` path. Test against the simulator first.
The original icon's prompt/provenance is recorded in `branding.md`.

## Boundaries and remaining risks

- **No hardware connection or physical command was made during this HA work.**
  New negotiation/control behavior is simulator-only. Earlier passive captures do
  not validate CTS latency, allocation or physical writes. BWAlink must be
  confirmed stopped again before a separately coordinated Elfin test.
- The `raunosr/ha-balboa-rs485` repository remains private. HACS requires public
  repositories; this package is not HACS-listed or certified. No public release,
  brands submission, merge or default-branch change was performed. Publication
  and selection of a distribution license need separate approval.
- Use one entry/client per physical controller. DNS aliases cannot be reliably
  deduplicated without a verified hardware ID. Reconfigure to preserve identity;
  deleting/recreating an entry creates new registry/history identity.
- Channel allocations may be finite. Runtime requests are bounded, but manual
  reloads or HA restarts start a new budget. Do not repeatedly restart an
  incompatible bus. Alternative/encrypted protocol families remain unsupported.
- Disputed filter-running and accessory/status interpretations stay conservative.
  Full fault events, writable clock/filter schedules and extra observation
  mappings are outside this basic package. Supplemental metadata is not continuous
  active-fault monitoring. Model/firmware are in diagnostics; the device registry
  currently uses the stable entry name and manufacturer.
- Tests are pinned to HA 2026.9.0, not every future HA release or Balboa controller.
  Rare framework-unload failures and watch timeout paths remain among uncovered
  branches. Coverage is evidence, not a physical safety proof.

Architecture review: protocol parsing and command arbitration remain in the
independently tested core; HA owns lifecycle/presentation and never sends raw
toggles. ZIP installation is tested independently of the source checkout.
The main remaining risk is physical bus/firmware compatibility, requiring the
separately staged hardware plan. Phase 5 heating-session intent, expiration,
persistence and restart restoration have not been implemented.
