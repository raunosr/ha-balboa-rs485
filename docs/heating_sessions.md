# Heating sessions (Phase 5)

Version 0.0.5 is simulator validated; see [the Phase 5 review](phase5_review.md).
Target Home Assistant 2026.8.3. These are timed setpoints, not a heating-time
prediction or a guarantee that the water reaches temperature before the deadline.

## Actions

Choose the spa's integration entry with the action's **Spa** selector. Each action
requires `config_entry_id`; there is no implicit "first spa" selection.

```yaml
action: balboa_rs485.start_heating_session
data:
  config_entry_id: YOUR_BALBOA_CONFIG_ENTRY_ID
  target_temperature: 38
  maintenance_temperature: 27
  temperature_unit: C
  duration: "10:00:00"
```

The duration starts immediately, including preheating. Instead of `duration`,
provide `end_time: "18:00"` (the next occurrence in HA's timezone) or an ISO
datetime with an explicit UTC offset. Never provide both. DST-ambiguous or
nonexistent local times are rejected; an explicit offset removes the ambiguity.

The unit defaults to `C`; select `F` for a Fahrenheit spa. Both temperatures must
match the currently observed spa unit, range and step. No automatic conversion,
range change, heat-mode change or unlocking is performed.

`extend_heating_session` and `reduce_heating_session` change the existing end
time by `duration`, defaulting to 30 minutes. Reduction past the present starts
restoration. Expired or cancelled sessions cannot be extended back into heating.
Starting a second session while one is active is rejected.

`cancel_heating_session` requests the saved maintenance setpoint. It does not
turn off the heater or cool the water actively. A manual HA climate temperature
change instead abandons the session, preserving your new manual setpoint.

## Persistence and safety

Actions save session intent through HA Store before starting physical work.
Storage is checked by reading it back. A storage failure blocks session writes
and is reported; it must not be treated as a successful heating request.

Session intent and connection binding are stored: temperatures, unit, start/end
timestamps, session phase and the entry's connection settings.
No raw frames, toggles or transport command queues are saved. Reload/HA restart
reloads intent, checks expiry first and reconciles fresh observed state.

Time keeps running during a connection outage or while physical controls are
disabled. Expiry requests maintenance, but no command is sent until controls are
enabled and fresh safe state is available. If the units/range no longer support
the saved value, restoration remains blocked rather than guessing a conversion.

Do not run competing spa clients. These software safeguards do not replace
separately coordinated hardware validation. Installation, HA restart and actual
spa control require user approval in this project.

The timer runs in HA, not in the spa. See the [installation and safety guide](home_assistant.md#heating-sessions-phase-5)
for sensor states, blocked reasons and shutdown/removal precautions.
