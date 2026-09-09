# 0.0.17 reliability correction

## Scope and evidence

Energy estimation and automation migration are deferred. This release addresses
reported v0.0.16 control rejection, confusing historical Priming messages and
incomplete cleanup after a failed HA entity-platform unload. No EW11 setting or
bus transport policy is changed.

A bounded passive read (zero application TX) found normal running state, no
current priming, and reminder code 3. Replaying that status through v0.0.16's
actual validator reproduced the user's "fresh synchronized normal operating
state" error. Existing recognized pH/sanitizer reminders were also unnecessarily
blocked. [Balboa's TP700/BP manual, printed pages 34–35](https://www.balboawater.com/wp-content/uploads/2024/12/TP700-user-guide_42370-rev-A_English.pdf)
identifies M03 as filter replacement. Applying that BP-family meaning to the
observed initialization/reminder flag combination is an evidence-backed protocol
interpretation, not proof for every Balboa model.

Known reminder codes 3, 4, 9 and 10 with the exact routine-reminder notification
flags now permit normal controls. Unknown notifications, active priming, Hold,
locks, unsynchronized state and fault flags remain blocked. Admission never
acknowledges or clears a reminder. The [wire reference](https://github.com/ccutrer/balboa_worldwide_app/wiki)
documents the other reminder codes and notification/state flags.

HA reported `failed_unload`, removed entities and platform errors, while diagnostics
still showed a live READY connection. A real-HA regression test reproduced this:
returning false from platform unload skipped the previous connection cleanup.
Another test reproduced a failed observation task preventing socket cleanup.
Cleanup now closes the physical owner first, rejects new commands, remains
idempotent for concurrent stop/unload, and closes the socket even when background
cleanup raises. A platform failure is still reported honestly, not masked.
These are integration defects; they do **not** establish the cause of a whole-HA
or host crash, and no such crash is deliberately reproduced on production.

## History versus active state

The controller's latest fault-log entry was code 19, Priming. This is historical,
not the current operating mode. The live priming binary sensor remains driven by
status messages. The historical entity retains its last observed entry across
connection gaps and is labelled "Latest historical log entry"; its Priming value
is explicitly marked historical. Existing entity IDs remain unchanged.

Diagnostics now expose current priming, Hold, reminder code/meaning, notification
flags, lock states and the control-blocking reason separately from historical logs.

## Activity clock noise

HA 2026.8.3 logs string-valued clock sensors and `time` controls by default.
There is no supported per-entity integration opt-out in its logbook platform.
Use HA's targeted `logbook.exclude.entities` for the spa-clock sensor and clock
control to suppress ticking without disabling controls or deleting Recorder
history. Merge with existing logbook configuration; never replace other filters.
Do not exclude all Balboa events: actual control and safety changes remain useful.
No fake units/state classes or modifications of HA internals are used.

## Validation and acceptance gates

- Red baseline: three core reminder cases failed; real-HA tests independently
  reproduced the failed-unload writer and failed-observer cleanup defects.
- Regression coverage includes routine reminders versus safety interlocks,
  native climate services in classic and explicitly opted-in direct modes,
  historical entry retention during a lab connection gap, and failed/concurrent
  cleanup. Failure injection is restricted to the simulator/HA test environment.
- Full core, real-HA, isolated HACS ZIP, typing and lint checks are release gates.
- Hardware acceptance requires a fresh stopped-competing-client check, HACS
  activation and a bounded reversible native control confirmed from observed
  state. Download success alone is not acceptance. No unattended-use claim.

Deployment and accepted restart counts are recorded privately. Pre-deployment
checkpoint: no restarts used from this bug-fix round's new two-restart allowance.
