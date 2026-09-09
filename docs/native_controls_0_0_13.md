# Native controls and observations — 0.0.15

0.0.15 correction: filter confirmation can re-read an early mismatching response,
with at most three total queries including lost-response retries. The default
filter confirmation deadline is nine seconds so its query budget can finish.
It never repeats the physical write or extends a sent deadline. Pump/toggle
deadlines and allocation limits are unchanged. Hardware retest remains pending;
see [filter confirmation review](filter_confirmation_review.md).

0.0.14 correction: two-speed pumps can confirm their already-observed final goal
when filtration skips intermediate OFF. BP6013G2 filter-running sensors now use
the source layout selected by an observed natural Cycle 2 end: mask 0x08 for Cycle
2, source-inferred 0x04 for Cycle 1. Other models retain consensus/unknown behavior.
See `phase4b_review.md` for hardware acceptance and current installed version.

This is the complete supported native entity implementation for Phase 4B. See
`phase4b_review.md` for laboratory versus production acceptance. It preserves
existing entry, device and entity identities; no MQTT entities or automations
are removed or migrated. The original local icon and HACS-compatible layout remain.

## Everyday controls

- Climate: measured water temperature, observed setpoint and heater activity;
  Low (maintenance) / High (bathing) presets select the controller's independently
  stored profiles. The inactive target is never guessed or silently read by
  switching profiles. Select a profile to edit its target.
- Pump 1: named Off / Circulation (1) / Jets (2), plus its existing fan entity.
  A single-speed model instead offers Off / On. Other pumps retain their native
  speed controls, with only supported speeds. A speed label is not a flow sensor.
- Supported lights, blower, auxiliary outputs and mister are discovered from
  capabilities. Unsupported hardware is omitted, not represented by fake controls.
- Ready / Rest policy is separate from temperature range. Ready-in-Rest is an
  observed transient, not a selectable permanent mode. Rest is not power-off.

## Bathing session

Use **Bathing duration** (minutes, default 120) and **Minimum bathing temperature**
(Celsius, default 36.5), then **Start bathing**. End and +/-30-minute buttons are
on the same device. These two number settings are HA preferences, not claims about
the current physical spa target. The matching service accepts duration or an
absolute deadline.

The session activates High, observes and durably saves its original target, raises
it only if below the minimum, and temporarily selects Ready. A higher High target
is never lowered. At expiry/end it restores its owned High target, original range
and heating policy; Low's target is not changed. Fahrenheit minima round upward
to a representable whole degree. Ready-in-Rest restores its underlying Rest policy.

Each physical step has a durable checkpoint. Reload/restart and network recovery
first check expiry; an expired session restores instead of reheating. If HA or the
gateway is offline at expiry, restoration must wait: **no timer is programmed into
the spa**. Intent, deadline, original settings, ownership and blocked reason are
visible in the session sensor and downloaded diagnostics.

Manual High temperature edits keep the user's new value, end the session and
restore only still-owned range/mode settings. Conflicting physical-panel edits
stop automatic overwrites. End normally restores; the explicit **Abandon heating
session restoration** action requires `confirm: true`, forgets the intent and
sends no spa command. Range/unit/mode/Soak/Hold-entry changes are refused while a
session is active or restoring. Explicit Hold exit can unblock restoration after
Hold was entered at the physical panel. Do not force an exit from priming or faults.

The older same-range `start_heating_session` action and version-1 stored records
remain supported. Its explicitly supplied maintenance target is distinct from
the new profile-aware bathing workflow.

## Filter schedules

Each cycle has native **Start** and **End** time controls and a read-only duration.
Cycle 2 additionally has an enabled switch. These are spa-local HH:MM values,
not HA timezone conversions. Changing start alone retains duration; changing end
recalculates duration across midnight. Equal start/end is rejected because it is
ambiguous between zero and 24 hours. Observed zero/24-hour schedules can still be
displayed. Cycle 1 cannot be disabled by this API.

The `set_filter_cycle` action can change several fields together. Each edit reads
the latest complete schedule, changes one cycle, preserves the other and verifies
a new controller response. Edits are serialized. Cached data or an echoed write
is not confirmation. An unconfirmed write is not replayed after reconnect; inspect
the new readback before trying again. A physical panel can still race a transaction:
the controller protocol has no compare-and-swap operation.

## Clock, units and maintenance

- Clock: native minute-resolution time control; commands expire with their connection.
- Clock 24h: display-format preference without rewriting the time.
- Celsius/Fahrenheit selector: observed controller conversion; blocked during sessions.
- Hold: explicit enter/exit with fresh verification. Normal operation exits Hold
  only; it does not bypass priming, test states, locks or a fault.
- Soak: requests supported pumps off and verifies them. It does not disable the
  heater or dedicated circulation, promise physical flow has stopped, or start
  the HA bathing timer. Automatic filtration/heating can prevent pumps stopping.
- Acknowledge reminder: one recognized replace-filter/clean-filter/pH/sanitizer
  reminder in a safe status. A following reminder is not automatically cleared,
  and ambiguous acknowledgements are never retried. Unrecognized codes below 15
  with reminder-only flags are displayed as `none` and do not block controls;
  pressing acknowledge in that state sends nothing. Raw codes stay in diagnostics.
  Fault-code space (15+), fault/unknown flags, priming and locks remain guarded.
  This compatibility default does not identify the meaning of unknown codes.

## Observations and diagnostics

Fresh passive water, heater state/running, range, mode, reminder, clock/format,
Hold, Priming and lock sensors remain available without a writable bus channel.
Stale readings become unavailable even if other traffic or the socket continues.
Dedicated circulation appears only when its capability descriptor is supported.

Both filter-running sensors are present. **Published source bit layouts conflict.**
For the identified BP6013G2, the naturally observed Cycle 2 end selected mask 0x08;
Cycle 1 uses mask 0x04 from the same source layout and remains source-inferred.
Other models report unknown when the source interpretations disagree; agreeing
values are source consensus, not hardware validation. Attributes distinguish
these evidence levels and expose the raw flag byte. Do not use these sensors for
safety-critical automation or claim individually proven Cycle 1 acceptance.

Latest fault and fault-log count are historical, with original numeric code and
event age/time attributes. Unknown codes remain `unrecognized`. They are not an
active-fault alarm, current sensor A/B temperatures, or proof a prior fault cleared.
Setup/filter/fault metadata refreshes every five minutes through the same owned
connection, not a second polling client; status observations remain streaming.

Connection/channel/CRC/recovery/allocation sensors and redacted downloads expose
transport health, timings, metadata, supported controls, filters, historical fault,
session restoration, prediction model and bounded verified-command history.
Controller model/software come from its information message, not BWALink's version.
Counters cover this runtime. The finite three-allocation safety budget is unchanged;
short acceptance is not a completed weak-WLAN 72-hour soak.

No invented pH, sanitizer concentration, measured flow, watts, kWh or EW11 RSSI is
provided by these standard spa frames. No factory setup/reset, GFCI test or lock
bypass controls are exposed. Unsupported manufacturer preferences remain research,
not guessed hardware commands. [EW11 recommendations](ew11_settings.md) include
the tested 10 ms Gap Time; no WLAN repair or EW11 configuration change is required
to install this update.
