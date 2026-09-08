# Phase 5: durable heating-session intent

Scope: timed heating sessions, native Home Assistant actions and status, safe
expiry/restart, and simulator tests. No prediction, energy, frontend, or hardware
connections. The Python core remains independent of Home Assistant. The user
confirmed HA 2026.8.3 after rolling back 2026.9; CI and the minimum version now
target 2026.8.3 (pytest-homeassistant-custom-component 0.13.357).

## Contract

- A session begins immediately. Its duration includes preheating. Alternatively,
  specify a timezone-aware end datetime or the next local `HH:MM` occurrence.
  Ambiguous/nonexistent local times are rejected; use an explicit UTC offset.
- Target and maintenance temperatures use the explicitly selected unit (`C` by
  default, or `F`). Both must match the spa's current unit and supported range.
  The integration never changes the range, units, or heating mode automatically.
- Only one session per entry. Starting another requires ending the existing one.
  Extension/reduction defaults to 30 minutes. Expired/cancelled sessions cannot
  be extended back into heating, even after a backward wall-clock adjustment.
- Cancel requests maintenance temperature. A manual HA climate setpoint instead
  durably abandons the session and then applies the user's new temperature.
- Expiry continues offline or with controls disabled. Restoration waits for
  fresh safe observations and enabled controls. Reaching the deadline is latched.
  A session completes only when the maintenance setpoint is actually observed.
- Pure immutable intent transitions expose idle, preheating, target_reached,
  holding, and restoring. These are not optimistic physical heater states.
- A per-entry HA Store saves intent before commands, using atomic writes and a
  fresh-Store readback to detect the Store API's logged-but-swallowed write errors.
  Invalid storage blocks session writes, not ordinary read-only spa observations.
  Unload preserves storage; deletion removes the entry's storage.
- Restart loads intent, checks the deadline first, then reconciles fresh state.
  No raw frames or command queues are persisted. Only the existing command engine
  may execute a desired temperature. One session command at a time; cancelled
  waiters retain the engine's physical ambiguity guard.
- `SessionRunner` owns persistence ordering, one goal per deadline/phase/epoch,
  cancellation, and reconciliation; HA supplies Store, wall time, and a 250 ms
  periodic tick. The runtime rechecks a synchronous admission guard immediately
  before transmission, so expiry, disabled controls, shutdown, or a new connection
  epoch invalidate an already queued session goal even between scheduler ticks.
- A target changed on the physical panel is reported as `setpoint_changed`, not
  continuously overridden. Explicit adjustment/cancel or a fresh connection epoch
  allows reconciliation again. An explicit HA climate setpoint abandons the session.
- Persistence is bound to the entry's connection settings. Reconfiguring an active
  session to another endpoint blocks restoration there; it never heats the new spa.
  Invalid/corrupt storage is fail-closed and visible in the session sensor.
- An in-flight transaction or unresolved resynchronization prevents declaring
  maintenance restored from a pre-send observation. Storage failure stops session
  writes; it cannot undo a physical command already sent.

## Vertical test-first slices

1. Pure start/expiry/observed restoration; then adjustment, cancellation, unit and
   range checks, phase progress, record validation and restart.
2. Store/controller lifecycle against actual HA and loopback simulator, including
   offline expiry, write failures, disabled controls, manual override and restart.
3. Global actions, input/time validation, entity translations, diagnostics, YAML
   packaging and extracted ZIP installation.
4. Full core and actual HA suites, branch coverage, lint/type checks, release ZIP,
   documented review. Stop at Phase 5.

## API references

- [HA action registration](https://developers.home-assistant.io/docs/dev_101_services/):
  register in `async_setup`; unavailable entries raise `ServiceValidationError`.
- [HA 2026.8.3 storage implementation](https://github.com/home-assistant/core/blob/2026.8.3/homeassistant/helpers/storage.py):
  `Store.async_save` logs some write errors without raising; a successful await
  alone is not proof of durable storage. Never start actions during HA shutdown.
