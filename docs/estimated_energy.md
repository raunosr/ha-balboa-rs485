# Estimated electricity consumption

Optional **observed actuator states × configured electrical input watts × time**.
This is not a meter, calibrated historical model or temperature-derived heat-loss
estimate. It sends no commands. Controls and heating prediction are unchanged.

## Setup and defaults

Enable **estimated electricity consumption** in integration options and continue
to the power form. It is off by default. Review the electrical input ratings of
your equipment, not hydraulic output. Saving does not reconnect. Already accrued
kWh survive changes of ratings and disabling/re-enabling the estimate.

| Load | Initial power | Qualification |
| --- | ---: | --- |
| Heater | 3000 W | Example installation; adjustable |
| Pumps 1–6, high / single speed | 1300 W each | Example installation; adjust other models |
| Pumps 1–6, low speed | 350 W each | Assumption, not measured |
| Separate circulation pump | 250 W | Assumption; counted only if reported as a dedicated pump |
| Light circuits | 10 W each | Assumption; only while on |
| Electronics | 20 W continuously | Allowance, not a statistical error bound |
| Blower, mister, auxiliaries | 0 W | Unconfigured; an active zero-rated load suspends accounting |

Only installed, observed loads are counted. Pump 1 LOW is **not counted twice**
as a separate circulation pump. Single-speed pump states use the existing
normalization. The blower uses one configured rating at every nonzero speed;
this is a simplifying assumption. Unknown actuator states or circulation
descriptors suspend accounting. A zero rating on any active load except electronics
also suspends accounting: zero does not invent a free heater or accessory.
Equipment missing from the controller descriptor cannot be included automatically.

Analytical examples, lights off:

- Heater + pump 1 LOW + electronics: **3370 W**, **3.37 kWh per observed hour**.
- Heater + three high-speed pumps + electronics: **6920 W**, **6.92 kWh per hour**.

These are not measured spa results.

## Entities and Energy Dashboard

- **Estimated power:** W, `device_class: power`, `state_class: measurement`.
- **Estimated energy:** lifetime kWh, `device_class: energy`,
  `state_class: total_increasing`. Select this under Energy → Individual devices.

Both entities have stable IDs even when estimation is disabled. Recorder/statistics
must include the kWh entity; it may take a statistics cycle before it is selectable.
Do not account for the same spa twice using another energy integration.
See [HA sensor metadata](https://developers.home-assistant.io/docs/core/entity/sensor/)
and [individual device energy](https://www.home-assistant.io/docs/energy/individual-devices/).

## Gaps, persistence and accuracy

Left-rectangle integration uses previous observed power between successive fresh
status frames in the same connection epoch. An interval over eight seconds,
reconnect boundary or unknown endpoint observation is excluded **in full**.
It is neither extrapolated nor treated as known zero consumption. Routine metadata
refresh may retain fresh same-epoch observations; lost synchronization may not.
Disabled periods and HA downtime are never backfilled.

Every 30 seconds the adapter atomically checkpoints changed totals in HA Store.
Only saved, verified totals are published. Normal unload also saves after releasing
the bus; HA final-write handles stopping. Only totals are restored, never a live
sample. During network outages power is unavailable and committed kWh stays frozen.
Sudden process death can lose the uncommitted tail but cannot lower a previously
published total because of that tail. Storage errors retain the published value
and appear in diagnostics. An unreadable existing record is not replaced by zero.
Deleting/restoring counter storage from an old backup can still lose history;
preserve HA backups and do not manually reset its energy Store.

The kWh entity attributes and downloaded diagnostics include ratings, observed
seconds, excluded runtime seconds and storage status. Coverage updates at checkpoints,
not every frame. Excluded runtime seconds describe gaps between runtime samples,
**not all HA downtime or disabled time**. Rating changes do not recalculate history.

Outdoor temperature and water volume are not needed here: their effect on heater
runtime appears in the observed heater-on time. The separate heating-time forecast
can still use an outdoor sensor. This feature does not claim historical calibration
or a verified 10–20% error. Pump load, voltage, guessed accessory ratings and missing
telemetry can cause substantial errors. Weak connections bias totals low. Compare
against a real meter before relying on accuracy.

## Verification and scope

Analytical tests cover ratings, six pumps, circulation, unknown states, gaps,
duplicate timestamps, epochs, profile boundaries and restoration. Actual HA tests
cover options, entity metadata, storage faults, background checkpoints and a
loopback-only simulator with physical controls disabled. Execution results are
recorded after the full suite. No production installation/acceptance is claimed.

This is only the requested estimate subset of Phase 7. External measured energy,
pricing, cost statistics and automation migration remain separate.
