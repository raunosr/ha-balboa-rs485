# Phase 6 — observational heating prediction

Scope: independent plain-Python segment collector, recency-weighted regression,
versioned persistence, numerically integrated ETA, HA sensors/options, and held-out
thermal simulation. Predictor never sends a command or owns a socket. Production
control availability and its channel-budget limitation remain independent.

## Data and model contract

- All model temperatures are Celsius. HA converts external C/F sensor values;
  missing, invalid or stale configured outdoor readings invalidate training.
- Continuously observed HEATING only; no learning from heater waiting/off, degraded
  connections, unknown temperatures, backward time or gaps exceeding 90 seconds.
- Non-overlapping windows normally last 60 minutes, minimum 30 on normal heater
  stop, maximum 90 when rise is too small. Require >=1 C rise to limit 0.5 C
  quantization noise. Estimate slope over the window, not from raw-point deltas.
  Reject unreasonable jumps/cooling/rates; discard interrupted windows on reload.
- Regression predicts C/hour from mean water-air delta, or mean water temperature
  when no outdoor entity is configured. Each window is one weighted sample;
  exponential forgetting favors recent windows. Degenerate fits use the weighted
  mean; constrain the physical slope to non-positive. Insufficient data uses an
  explicitly configured fallback rate and reports learning.
- Integrate with <=0.1 C midpoint steps. Invalid/nonpositive learned rates mean
  no reachable ETA, not an invented positive rate. ETA assumes continuous heating;
  ready-at is only offered while actually heating (or target already reached).
- Track pre-update segment ETA errors, not in-sample fit error. Expose rolling MAE,
  median absolute error and sample count; identify segment-error scope and do not
  display confidence percentages. Held-out full-session evaluation is separate.
- Store sufficient statistics, coefficients, sample count, recent errors and last
  update with a version and endpoint/model-feature binding. Model failures must not
  break control/session lifecycle. Never persist incomplete windows or wire data.

## Delivery/test slices

1. Collector validation and quantization/window boundaries.
2. Regression, persistence validation, numeric integration and adaptation tests.
3. Deterministic physical thermal generator: 60 days, independent held-out sessions,
   +10/0/-10/-20 C ambient; report MAE, median absolute error and signed bias.
4. Optional outdoor entity/fallback options and five HA sensors, lifecycle/storage
   tests, no extra socket or physical command. Existing entity IDs remain unchanged.
5. Full tests/lint/types/bundle, self-review and bounded deployment acceptance.

User-authorized Phase-6 Core restart budget: two; none used at phase start.
Restart 1/2 was requested 2026-09-07 18:43:30 UTC for 0.0.10; see the review.
Restart 2/2 was requested at 19:04:11 UTC for the tested 0.0.11 options-form fix.
No restart, HA/OS upgrade or network fault is needed for model development.
