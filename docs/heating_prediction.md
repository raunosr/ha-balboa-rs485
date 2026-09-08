# Heating prediction

Version 0.0.11 adds five entities to the existing Balboa device. Predictions are
observational: enabling them never starts the heater or changes the target.

| Entity name (English) | Meaning |
| --- | --- |
| Heating rate | Estimated degrees Celsius per hour at the current water/outdoor temperature |
| Heating time remaining | Integrated estimate to the spa's current target, in minutes, assuming continuous heating |
| Ready at | Estimated timestamp while the heater is actually heating; unknown while off below target |
| Heating prediction error | Mean absolute pre-update heating-window ETA error in minutes, not a confidence percentage |
| Heating learning segments | Number of accepted clean heating windows |

Names follow the HA language; equivalent Finnish translations are included. These
are native entities, available to history, dashboards and automations without a
custom card. Error and learning count are in the device's Diagnostic section.

## Initial learning and options

Open the integration's options. **Initial heating estimate** defaults to 2 C/hour
and can be changed within 0.1–8 C/hour. Until five valid windows are collected,
the sensor attribute `prediction_quality` is `learning` and that initial estimate
is used. It is not a measured rate or an accuracy promise. Afterwards it is
`learned`; the lightweight regression adapts as more windows arrive.

Choose an **optional outdoor temperature sensor** reporting Celsius or Fahrenheit.
It must have a fresh update within 15 minutes. Missing, unavailable, invalid or
stale configured outdoor data makes ETA unknown and stops learning that window.
Leave the selector empty to learn from water temperature alone. Changing/removing
the selected sensor resets the model, since the features no longer match.
Changing these options does not reconnect the spa or enable physical controls.

The model needs uninterrupted, observed active heating, normally a 60-minute
window (30 minutes minimum on a normal heater stop, 90 maximum) and at least a
1 C rise. Small maintenance pulses therefore may not add training windows.
Routine healthy metadata refresh does not interrupt learning. Actual degraded
traffic, reconnects, invalid temperatures or observation gaps discard the current
window. The learned model survives reload/restart; unfinished windows do not.

## Limits and diagnostics

ETA assumes the current target and continuous heating; it cannot anticipate an
opened cover, changed weather or a future heating schedule. The ready-at timestamp
is not a guarantee. A physically unreachable/out-of-model target gives unknown,
not an invented positive heating rate. The actual spa remains authoritative.

Attributes show the model feature, learning state, error scope, last model update,
median absolute error and storage error flag. Downloaded integration diagnostics
also include model coefficients and sample count, without the outdoor sensor ID
or endpoint. Model storage failure does not disable physical controls or sessions.

The deterministic 60-day thermal test achieved 7.24-minute held-out mean absolute
error and 7.28-minute median absolute error. This evaluates synthetic full heating
sessions, not this spa's real accuracy. Runtime error is calculated on prior
heating windows before learning from them. See [review](phase6_review.md).
