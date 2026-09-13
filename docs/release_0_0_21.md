# v0.0.21 — Optional electricity estimate

Experimental HACS release. Requires Home Assistant 2026.8.3 or newer.

- Adds **Estimated power** (W) and persistent **Estimated energy** (kWh), with
  Energy Dashboard-compatible metadata.
- Optional, disabled by default. Enable in integration options and review heater,
  pump, circulation, light and accessory electrical input ratings.
- Uses observed actuator states, not commands or optimistic state. No extra spa
  writes. Pump 1 low speed is not counted twice as a dedicated circulation pump.
- Preserves saved totals across normal reloads/restarts and settings changes.
  Unknown states, connection gaps and HA downtime are not backfilled. Storage
  faults cannot block spa controls.

This is an estimate, not a meter: missing telemetry biases totals low and assumed
ratings can be inaccurate. No calibrated 10–20% accuracy is claimed. See the
[setup, defaults and limitations](https://github.com/raunosr/ha-balboa-rs485/blob/v0.0.21/docs/estimated_energy.md).

Verification: 712 core tests, 124 actual Home Assistant tests, isolated installation,
strict typing, lint, bundled-core and HACS validation. These are laboratory checks,
not real-meter calibration or all-control hardware acceptance.

This release does not include the separate pending priming/recovery correction,
historical energy training, pricing or automation migration. Existing control
limitations remain. HACS installation requires a normal Home Assistant restart to
activate the updated Python package; downloading alone does not activate it.
