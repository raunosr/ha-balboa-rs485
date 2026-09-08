# Weak-network diagnostics review — 0.0.6

Reviewed 2026-09-06. This is a bounded Phase 5 acceptance follow-up, not Phase 6
or a claim that production channel control is fixed. HA was on 0.0.5 at review;
the later approved 0.0.6 installation/restart is recorded in `hardware_validation.md`.

## Implemented

- Fresh decoded status can be inspected independently of control/configuration
  readiness. Stale/disconnected observations are not presented as current.
- HA receives staleness changes even when unrelated valid traffic continues.
- The existing two-second channel-assignment acceptance window now produces an
  explicit timeout reason. There is no automatic assignment retry or socket reset
  on that failure; allocation limits and all original write guards remain intact.
- Immutable aggregate diagnostics distinguish responses seen, correlated replies,
  and usable reply opportunities. They omit raw frames, endpoint data and nonces.
- Documented EW11 starting settings and paired Gap 50/10 measurements.
- Recorded native-entity gaps against the user's MQTT device screenshot.

## Verification

Code commit `7be332e6955ee40d0d7d510a0a77ca30de73d09e` passed
[private CI run 34052952001](https://github.com/raunosr/ha-balboa-rs485-private-archive/actions/runs/34052952001).

| Check | Result |
| --- | --- |
| Core Python 3.12 tests | 332 passed; 97.50% branch-inclusive coverage |
| Actual HA 2026.8.3 / Python 3.14 adapter tests | 50 passed; 97.19% coverage |
| Separate ZIP installation test | 1 passed |
| Ruff / format / strict core and adapter typing | Passed |
| Canonical/generated core equality | Passed |

Total: **383 passing tests**. The new TCP regression cases first reproduced the
missing timeout, then passed for absent, wrong-nonce and batched responses. HA
tests verify timeout propagation without additional status, and stale read-only
observations disappearing/reappearing in the same connection epoch. Existing
ownership, collision, command, reconnect and heating-session tests still pass.

Local archive: `dist/ha-balboa-rs485-0.0.6.zip` (excluded from Git), SHA-256:
`09c811289f054b2eb15b1cda0a36ca133c792825a4cd5df2be87ae97e7cd85ad`.

## Hardware boundary and next step

Gap 10 enabled one complete direct-core handshake/configuration synchronization
in 1.7 seconds, but two HA attempts each stopped after a single assignment request.
The HA-side root cause is still unproven. No physical controls were sent and no
production HA outage was induced. See `hardware_validation.md` for chronology.

Deployment requires a scoped integration-directory backup/replacement and a
**user-approved Core restart** to load new Python modules. Do not silently hot-patch
the running HA process. After approval, verify BWALink stopped, capture the new
aggregate failure evidence during one bounded HA attempt, and only proceed to
setpoint/session tests once ownership, configuration and fresh state are verified.
Do not repeat reloads to obtain a fresh allocation budget. WLAN repair is not a
prerequisite for continuing diagnosis. Phase 6 remains behind hardware acceptance.
