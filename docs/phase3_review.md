# Phase 3 review — 2026-09-05

Implemented: immutable capability-aware `SpaState`, independently encoded known
controls, latest desired values, one physical transaction in flight, observed
confirmation, coalescing, cancellation, bounded action budgets and last-100
transaction history. Supplemental setup/filter/last-fault observations retain
raw frames and unknown values. `SpaRuntime` composes state and command logic with
the existing socket lifecycle through a neutral participant interface.

Verification: **244 passed, 0 failed; 97.86% combined statement/branch coverage**.
Ruff checks/format and strict mypy passed (31 source files). Meaningful runtime
and error paths remain included in coverage. Tests were added incrementally
before implementation, including the mandatory safety failures. The eight real
TCP runtime tests also passed five consecutive runs (40 additional executions).

The built `ha_balboa_rs485-0.0.3-py3-none-any.whl` was imported directly with
Python isolated mode, independent of the editable source import path. Its
packaged simulator fixtures, configuration synchronization, metadata queries,
OFF -> LOW -> HIGH intent, two observed physical transitions and clean shutdown
passed a real loopback smoke check. Building without isolation initially found
no setuptools in the development venv; the normal isolated build succeeded.

## Mandatory lost-confirmation proof

The real TCP simulator applies the first pump toggle but drops subsequent status
on that connection while continuing CTS. The engine must time out confirmation,
record an ambiguous transaction, stop physical writes and fully resynchronize.

- Desired LOW: the new connection observes physical LOW; exactly one toggle was
  sent in total. No repeated toggle turns the pump HIGH accidentally.
- Desired HIGH: the new connection observes stable LOW; exactly one further
  toggle is computed from that observation, in the new epoch, then verified HIGH.
- Abrupt reset after applying a toggle follows the same state-aware recovery.
  No pre-serialized physical command survives the old socket.

Unit tests additionally cover buffered pre-command state, coalescing after TX,
cancellation/supersession across timeout, changed capabilities, invalid intents,
unknown physical states, stale observations, history eviction and action limits.
Single-speed raw-2 ON/OFF and supported accessories have real TCP coverage.
Scripted and interactive CLI subprocess tests exercise the same runtime; rapid
intent demos prove that bursts coalesce to the final value rather than raw toggles.

## Architecture and safety review

The Python core has no Home Assistant or third-party runtime dependencies. The
transport owns socket/CTS/epoch handling, not pump semantics. State updates come
only from decoded incoming observations; user requests and TX never mutate them.
The command engine uses explicit monotonic time. Diagnostics and retry attempts
are bounded, and active goals are not lost when diagnostic history rolls over.

CTS gating now also checks the raw stream tail: discarded garbage after a parsed
READY invalidates that opportunity. Partial READY frames still work. Queries and
physical commands share one fresh opportunity; no CTS credits accumulate. Sent
actions are recorded before awaiting socket drain, preserving ambiguous outcomes
on cancellation or failure. Interactive shutdown joins its network worker.

## Limits and next gate

All physical-command verification is synthetic and loopback-only. The user's
actual Elfin at a redacted LAN address, port 8899, was only passively observed in Phase 2, with
TX 0. Its addressed channel traffic is **not write-supported**; no channel
negotiation, ownership claim, hardware query or physical write was attempted in
Phase 3. BWAlink can remain in normal use. See `hardware_validation.md`.

TCP has no causal command acknowledgement or controller sequence number. The
post-TX guard and resynchronization settling span are explicit assumptions, not
proof against unbounded gateway delay or external panel changes. Hardware gates
remain mandatory. Disputed accessory bits and unknown/locked operating states
fail closed. Target limits require observed setup data and conservative bounds.
Fault data is the last observed log entry, not a claim of active/no faults;
periodic log polling, full log traversal and fault clearing are not implemented.

No HA integration, heating sessions, persistence, prediction, energy, frontend,
blueprints or long hardware soak is claimed. Phase 3 is complete and reviewed.
**Stop here; Phase 4 requires user approval.**
