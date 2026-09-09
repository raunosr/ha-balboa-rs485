# Pump request lifecycle and recovery follow-up

Status: 0.0.20 release candidate; not hardware accepted. Installation and activation
must be verified separately from publication.

## Reproduced boundary, not a diagnosis of wire loss

The later v0.0.19 report contains three ambiguous confirmation timeouts for a
Pump 1 HIGH-to-LOW goal, followed by successful later LOW/OFF requests. Thus the
earlier 13/13 short acceptance sequence is not all-control reliability acceptance.
The trace does not establish collision, controller refusal or gateway delay as
the cause. No new production command, restart, or gateway change was performed.

A deterministic TCP simulator now drops pump writes while continuing normal
status traffic. On the original implementation, a different pump goal submitted
during recovery raises `Connection is not READY for physical commands`, leaving
the previous goal active. This is the reproduced software admission defect, not
proof that the simulator models the physical cause of the original loss.

## Changes

- Native pump requests use a 30-second monotonic **whole-goal** deadline owned by
  the core and used by the HA waiter. Other native commands retain 20 seconds.
  Reconnection does not extend deadlines. No further transmission starts without
  enough remaining time for its confirmation window. Late observations can still
  resolve the physical receipt, but cannot turn an expired goal into success.
- Pump replacements preserve the original deadline and spent six-action budget.
  Identical native callers still join the same goal. Different values replace it,
  including during recovery, but only for a previously admitted, still-active pump
  goal. Cold/unrelated requests remain unavailable while disconnected.
- Cached capabilities can validate an incoming replacement's shape; they never
  authorize TX. Current synchronized state, locks, faults, configuration and
  circulation guards are re-evaluated by the existing planner. Old in-flight
  receipts and ambiguity/resynchronization barriers remain intact.
- A 150 ms unsent-goal coalescing window absorbs rapid slider edits. This is
  intent admission, **not** a fixed delay claiming RS485 bus ownership. Identical
  callers do not extend this window; replacement edits cannot extend the whole
  goal's deadline or reset its action count.
- `Pump 1 command` is a separate enum sensor with requested and observed speed,
  latest intent ID and reason. It stays visible during recovery. The existing
  speed slider remains observation-based; during an active recovery it accepts
  replacement goals but reports unknown current speed, not cached/optimistic speed.
  No countdown/per-frame attributes are added to entities.
- A superseded call is a translated `ServiceValidationError`, explicitly a
  replacement/cancellation, not a generic device fault or verified old target.
  HA can still show a notice; suppressing it by pretending the old command
  succeeded would silently change automation semantics. Service calls still
  complete successfully only for their verified goal.
- Diagnostics add a bounded 200-event semantic timeline: received goals, joined
  callers, stage transitions, replacements, cancellation, recovery and completion.
  It includes unsent goals missing from the TX-only history. Only allowlisted
  values and relative times are exported; no endpoint, credentials or raw frames.

## Validation scope

Core tests cover dropped writes with live RX, new targets during recovery in
classic/channel/direct modes, delayed application before/after reconnect,
deadline expiry, preserved ambiguity receipts, exhausted action budgets,
coalescing, invalid admission and bounded event memory. HA tests exercise native
number services, duplicate aliases, translated replacement outcomes, sensor
state, expiry and unload at the unsent coalescing boundary.

The delay tests are synthetic examples, not a proven upper bound on EW11 latency.
Arbitration/channel-allocation limits are unchanged. No unlimited raw-toggle
retry, automatic transport fallback, persisted pump requests or HA restart
recovery command replay is introduced. Sessions/automations and energy work are
outside this change; HACS download/live validation remains a separate gate.

The implementation head `645b29e0f3396c52a8cb0834a1c21ea1e4a8253f` passed
[CI](https://github.com/raunosr/ha-balboa-rs485/actions/runs/34389819632):
687 core tests (96.96% coverage), 113 actual HA framework tests (97.48% coverage),
and one isolated ZIP installation test: **801 passed**. Lint, core/HA typing and
HACS validation passed. Release metadata and documentation are prepared in the
same PR and must pass the required checks again before its normal squash merge.
