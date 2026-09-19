# v0.0.22 - Energy estimate circulation configuration

Experimental HACS release. Requires Home Assistant 2026.8.3 or newer.

- Fixes unavailable energy estimates caused by an ambiguous circulation-pump
  descriptor by adding an explicit, energy-only equipment setting.
- Choose **Automatic**, **No separate circulation pump**, or **Separate
  circulation pump installed** in the energy options. Automatic remains
  conservative; an unknown descriptor still requires equipment confirmation.
- For the documented Cello Spa Ounas configuration, Pump 1 provides low-speed
  filtration and heater circulation: choose **No separate circulation pump**.
  This avoids adding a fictitious separate-pump load.
- Preserves saved power ratings, accrued kWh and entity IDs. Changing the setting
  does not reconnect, reprice history or change physical pump controls.
- Adds diagnostic attributes explaining when an explicit circulation
  configuration is needed. Unknown actuator states and telemetry gaps remain
  excluded; missing water temperature alone does not prevent energy accounting.

## After installing

Download **v0.0.22** in HACS, enabling prereleases if needed, and restart Home
Assistant at a safe time to activate the updated Python package. Reuse the
existing integration entry; downloading alone does not load the update.

Open **Settings > Devices & services > Balboa RS485 > Configure**, keep the
estimate enabled, and review **Circulation pump configuration** and the electrical
input ratings. For a confirmed Ounas installation as described above, select
**No separate circulation pump**. Keep the electronics allowance appropriate to
your installation; an existing 40 W setting is preserved.

With known OFF loads and a 40 W electronics allowance, the estimate is 40 W and
accrues 0.04 kWh per observed hour. Energy totals are published after the periodic
checkpoint, not immediately. Previously excluded consumption is not backfilled.
The default 350 W Pump 1 low-speed rating is still an assumption, not a measured
Ounas specification.

See the [setup, defaults and limitations](https://github.com/raunosr/ha-balboa-rs485/blob/v0.0.22/docs/estimated_energy.md).
This is an estimate, not a meter. Verify electrical input powers against equipment
data or a real meter before relying on accuracy.

Required release checks cover core and actual HA regressions, isolated package
installation, strict typing, lint, bundled-core consistency and HACS validation.
These are laboratory checks; no real-meter calibration or new hardware acceptance
is claimed.

This release does not include the separate pending priming/recovery correction,
pricing, historical model training or automation migration. Publication performs
no HA installation, restart or physical spa command.
