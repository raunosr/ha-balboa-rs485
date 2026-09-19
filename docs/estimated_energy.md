# Estimated electricity consumption

Optional **observed actuator states × configured electrical input watts × time**.
This is not a meter, calibrated historical model or temperature-derived heat-loss
estimate. It sends no commands. Controls and heating prediction are unchanged.

## Setup and defaults

Enable **estimated electricity consumption** in integration options and continue
to the power form. It is off by default. Review the electrical input ratings of
your equipment, not hydraulic output. Saving does not reconnect. Already accrued
kWh survive changes of ratings and disabling/re-enabling the estimate.

Choose **Circulation pump configuration** for the estimate:

- **Automatic (controller configuration)** keeps the conservative protocol
  interpretation. An ambiguous descriptor suspends the estimate.
- **No separate circulation pump** counts the normal pumps at their observed
  speeds, without adding a separate circulation load. Use this when Pump 1 LOW
  provides circulation.
- **Separate circulation pump installed** counts its configured watts only while
  the observed circulation flag is on.

The explicit choices describe confirmed physical equipment, not a requested pump
state. They affect energy accounting only: command admission, pump controls and
protocol decoding are unchanged. Changing the choice breaks the current accounting
interval without resetting or recalculating accrued kWh. Existing entries default
to Automatic. The selector is available from v0.0.22; it is absent from v0.0.21.

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
descriptors in Automatic mode suspend accounting. A zero rating on any active load
except electronics also suspends accounting: zero does not invent a free heater or accessory.
Equipment missing from the controller descriptor cannot be included automatically.

Analytical examples, lights off:

- Heater + pump 1 LOW + electronics: **3370 W**, **3.37 kWh per observed hour**.
- Heater + three high-speed pumps + electronics: **6920 W**, **6.92 kWh per hour**.

These are not measured spa results.

### Cello Spa Ounas example

The [Ounas product specification](https://www.k-rauta.fi/tuote/ulkoporeallas-cello-spa-ounas/6438313561033)
lists one 1.3 kW two-speed pump, two 1.3 kW single-speed pumps and a 3 kW heater.
The [model's operating manual, pages 12–13](https://docs.keskofiles.com/f/btt/ASSET_PDF_24877486#page=12)
describes Pump 1 LOW as the filtration speed and Pump 1 circulation for heating.
For this documented configuration, choose **No separate circulation pump**;
do not add the default 250 W as another load.

The sources do not specify low-speed electrical input power. The initial 350 W
remains an assumption, and the published pump ratings should be checked against
electrical input/nameplate data or a meter. Set the electronics allowance to the
installation's actual standby allowance; the generic default is not a measurement.
For example, a 40 W allowance gives 40 W with all observed loads off, 390 W with
Pump 1 LOW at the assumed 350 W, and 3390 W with a 3000 W heater added. Known idle
operation would accrue 0.04 kWh per hour even without a water-temperature reading.

## Entities and Energy Dashboard

- **Estimated power:** W, `device_class: power`, `state_class: measurement`.
- **Estimated energy:** lifetime kWh, `device_class: energy`,
  `state_class: total_increasing`. Select this under Energy → Individual devices.

Both entities have stable IDs even when estimation is disabled. Recorder/statistics
must include the kWh entity; it may take a statistics cycle before it is selectable.
Do not account for the same spa twice using another energy integration.
See [HA sensor metadata](https://developers.home-assistant.io/docs/core/entity/sensor/)
and [individual device energy](https://www.home-assistant.io/docs/energy/individual-devices/).

Both entities expose `circulation_configuration` and
`circulation_configuration_required`. If the latter is true, Automatic could not
resolve the equipment descriptor: verify the spa's equipment and choose the
appropriate configuration in options. The same fields appear in diagnostics.
An unavailable estimate is not zero consumption; a stored total of zero with zero
observed seconds does not prove accounting is working.

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

The v0.0.22 circulation selector adds regressions for ambiguous descriptors,
40 W idle accounting, missing temperature, no double counting, unknown-load
guards, unchanged physical-control semantics, options persistence and interval
boundaries. Release requires the core, actual HA and HACS checks; the HA suite
runs on Linux / Python 3.14 / HA 2026.8.3. The execution counts below describe
v0.0.21, not the additional selector cases.

Analytical tests cover ratings, six pumps, circulation, unknown states, gaps,
duplicate timestamps, epochs, profile boundaries and restoration. Actual HA tests
cover options, entity metadata, storage faults, background checkpoints and a
loopback-only simulator with physical controls disabled. Execution results are
recorded in [PR14](https://github.com/raunosr/ha-balboa-rs485/pull/14).
Local full core: 712 passed, 97.05% coverage; energy accounting module 100%.
Ruff, formatting, strict core typing and bundled-core validation passed.
Required CI passed: 124 actual HA tests (97.76% adapter coverage; energy adapter
100%), one isolated installation test, HA typing and HACS validation.
Version 0.0.21 packages this optional estimate. These results are laboratory
verification, not production activation or calibrated energy acceptance.

This is only the requested estimate subset of Phase 7. External measured energy,
pricing, cost statistics and automation migration remain separate.
