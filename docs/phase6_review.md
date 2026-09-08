# Phase 6 review — heating prediction (0.0.11)

## Scope and safety

Independent Celsius model and quantization-aware collector; no HA imports, socket
or command dependency in the prediction core. HA adapter supplies fresh observed
water/heater state and optionally an external temperature sensor. Invalid or stale
input discards the current learning window. Incomplete windows are never restored.

Five native sensors are provided: estimated heating rate, time remaining, ready-at,
pre-update segment ETA mean absolute error, and learned-window count. Fewer than
five windows use the configurable initial rate (default 2 C/hour), explicitly marked
`learning`. No confidence percentage is fabricated. Ready-at is unknown while the
heater is off and water is below target; remaining time assumes continuous heating.

Learned windows trigger an atomic HA Store write; cancellation retains dirty state
for unload retry. Orderly HA shutdown uses Store's final-write support, not a false
readback failure. Corrupt/unwritable model storage is visible in diagnostic attributes
and does not block physical control/session lifecycle. Sensor/endpoint changes never
reuse the wrong learned coefficients. No existing entity ID is renamed.

## Evaluation and tests

- Local full suite: 387 passed; combined core/tool branch coverage 97.69%.
- Predictor coverage 98.86%; thermal oracle 100%.
- Ruff lint/format and strict core typing pass.
- Held-out deterministic physical simulation: 60 days, 45 training and 15 test days,
  seed 20260907, outdoor +10/0/-10/-20 C, 301 accepted training windows.
- Test-day full-session MAE 7.24 min; median absolute error 7.28 min;
  signed bias +5.05 min; maximum absolute error 14.92 min.
- These are simulator results, not a claim of this owner's spa accuracy. Runtime
  error metrics cover pre-update heating segments, not full-session validation.
- Real HA 2026.8.3: 67 lifecycle/storage/options/entity tests, 97.91% adapter
  branch coverage; one separate extracted-ZIP installation test passes.
- All 455 tests, lint, strict core/adapter types and bundle checks passed in private
  CI [34152509531](https://github.com/raunosr/ha-balboa-rs485-private-archive/actions/runs/34152509531),
  code revision `d118984064be87335e6902e1b13f87ca209f5876`.
- Additional review caught periodic metadata synchronization breaking every
  learning window: a regression test now spans those healthy same-epoch refreshes.
  New-epoch/initial synchronization and degraded traffic still invalidate learning.
- Production 0.0.10 installed with all 43 files verified; previous 0.0.9 retained
  under `/config/.balboa-backups/`. Archive SHA-256:
  `f1d4d3d18488914a6640091a44cfa883fcabe4604268c0c60c563170c50b0a77`.
- Phase-6 restart 1/2 requested 2026-09-07 18:43:30 UTC. HA 2026.8.3 RUNNING
  verified 18:48:54 UTC. BWALink stopped; Balboa enabled once and READY on channel
  26, epoch 1, one assignment request. Five forecast entities present, water/target
  37 C, session idle, no physical commands, no prediction storage error.

### Options UI regression caught during production acceptance

The MCP options probe failed and HA logged `Unable to convert schema: finite_rate`.
The original tests called the flow manager but did not serialize its form as the
HTTP/UI layer does. An exact-source minimized reproduction with HA's pinned
voluptuous 0.15.2 / voluptuous-serialize 2.7.0 reproduced the same error locally.
This direct named exception justified skipping broad transport hypotheses.

0.0.11 removes the extra validator and uses HA's serializable native numeric range
constraint, which already rejects NaN/infinity. An intermediate test incorrectly
expected NaN to reach the handler; CI caught the earlier native rejection and the
test was corrected to expect that exact API exception. The permanent HA test now
serializes the displayed form with the actual HA custom serializer and checks NaN
rejection without changing entry options. Local reproduction turned green.
No production instrumentation or unrelated configuration change was needed.
The remaining acceptance at that checkpoint was fixed CI, installation, the final
authorized restart and the real options/schema probe, completed below. This UI
defect did not affect forecast calculations or physical commands; 0.0.10 was not
declared complete.

Final 0.0.11 code revision `5275f36757ecc1914359266edbf38d919a06deec` passed all
455 tests in [CI 34153769564](https://github.com/raunosr/ha-balboa-rs485-private-archive/actions/runs/34153769564):
387 core (97.69%), 67 HA (97.89%), one extracted-ZIP installation test, plus
lint, strict core/adapter typing and bundle equality. The fixed 43-file package
was installed and byte-verified; the previous 0.0.10 directory was retained.
SHA-256: `1d9e3e5c2687deaf8d78c2ef6625abd72501722969528728471d0a1630805a94`.
Phase-6 restart 2/2 was requested at 2026-09-07 19:04:11 UTC. No further Core
restart is authorized without new permission.

### Final production acceptance — complete

At 19:10 UTC HA 2026.8.3 was verified RUNNING and BWALink stopped. Balboa was
enabled once. At 19:11 the real HTTP options-schema probe succeeded without the
previous serialization warning. A bounded options round trip changed only the
fallback rate 2 -> 2.5 -> 2 C/hour; both the persisted option and rate sensor were
read back at 2.5 and the final sensor/diagnostics confirmed 2.0. Controls stayed
disabled and no outdoor entity was selected. The options changes did not create
a new connection epoch.

At 19:12:19: READY, channel 27, epoch 2, two assignment requests, one automatic
recovery, CRC errors 0, discarded bytes 38. This was not an error-free initial
connection. Water/target 37 C, heater off, session idle, physical command history
empty. All five prediction entities were present, remaining time 0 min, learning
windows 0, error unknown, storage_error false. No real heating window has yet
validated prediction accuracy on this spa. The bounded Balboa system-log query
returned no entries; this is not a whole-system log audit.

The browser confirmed version 0.0.11, 12 native entities, the five forecast/model
sensors in Sensors/Diagnostic, and existing climate, three pumps and light.
Phase 6 implementation and bounded installation acceptance are complete. Both
Phase-6 Core restarts are used; additional restarts require new authorization.

## Remaining work outside this phase

Long-duration channel assignment-budget recovery remains an open final-acceptance
limitation. Phase 4B is explicitly scheduled immediately after Phase 6 and before
Phase 7 to close the supported native entity/control/diagnostic gaps; see
`entity_parity.md`. A successful forecast does not imply full MQTT feature parity.

HA API references: [sensor entities](https://developers.home-assistant.io/docs/core/entity/sensor/),
[2026.8.3 Store implementation](https://github.com/home-assistant/core/blob/2026.8.3/homeassistant/helpers/storage.py).
