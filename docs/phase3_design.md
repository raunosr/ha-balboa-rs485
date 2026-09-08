# Phase 3 — observed state and desired-state commands

The user authorized this phase after Phase 2, which is reviewed in
`phase2_review.md`. No HA, sessions, predictor, energy or frontend in this phase.
The user's real Elfin shows channel traffic and remains write-unsupported. All
physical-command testing in this phase is restricted to the loopback simulator.

## Boundaries and approved behaviors

- Protocol: independently encode known BF20 absolute target and BF11 item toggle
  messages. Add typed setup/filter/fault observations, preserving unknown fields.
- State: immutable `SpaState` derived from incoming status and configuration,
  with capability-aware controls. Never mutate physical state on request or TX.
- Command: desired values per control, latest-intent coalescing, one physical
  transaction in flight, expected next observation, bounded transaction history.
- Runtime: compose state/command with the existing transport through a neutral
  synchronous participant interface. Transport owns socket and CTS consumption;
  it never learns pump behavior. No pre-serialized command queue survives an epoch.
- Simulator: shared synthetic physical state, real control effects, dropped
  confirmation, rapid intents and connection-loss scenarios. Interactive smoke
  commands call the same desired-state engine, with an explicit loopback-only flag.

## Confirmation and ambiguity policy

Every transmission records epoch, observation sequence, starting physical value,
expected next value, selected CTS timestamp, actual TX timestamp and intent id.
Only a later incoming status can verify it. A configurable minimum post-TX age
rejects immediately buffered status; unchanged pre-send values do not prove that
a toggle failed. A new desired value never cancels knowledge of a sent physical
action. It supersedes intent, then waits for that action's observation.

On confirmation timeout: mark the physical transaction failed/ambiguous, request
a full connection/configuration resynchronization, and send no further physical
action in that epoch. Preserve desired values, not prepared frames. After a new
epoch is READY, require fresh stable observations spanning a settling interval,
then recompute from capability-aware physical state. Desired LOW + observed LOW
needs no TX; desired HIGH + observed LOW may need one new CTS-gated toggle.

TCP provides no controller sequence number or causal acknowledgement. A settling
interval is an explicit policy assumption, not proof against arbitrary gateway
delay or external panel activity. Hardware controls remain gated pending capture
and validation. Never treat repeated stale OFF reports as permission to blindly
retry within the same epoch. Unknown raw states or changed/removed capabilities
block/fail the intent rather than inventing a toggle count.

## Scope of controls

Support target temperature with observed setup bounds, six agreed pump slots,
unambiguous light mappings, heat mode/range and other accessory controls only
where both capability and observation mappings agree. Single-speed pump raw 2
maps to ON; raw 3 is unknown unless explicitly supported. Light raw 1 is ambiguous
between references and cannot authorize a toggle. Expose unsupported/absent
values as unknown, not inferred OFF. Filters/faults are observations, not setters
or clear-fault actions. Priming/hold/unknown operating modes inhibit controls.

Test slices: state mapping -> one observed pump transition -> lost confirmation
LOW/HIGH cases -> coalescing and absolute target -> lifecycle cancellation and
configuration changes -> CLI/simulator scenarios -> full review and stop.

## Implemented policy details

Default confirmation guard 0.2 s; confirmation deadline 4 s; post-resync stable
observation span 0.5 s, with at least two distinct status sequences. Engine rejects
state older than 3 s independently of transport availability. All are injectable.
At most six physical actions per intent (including recomputed actions after
resynchronization); exhaustion fails the intent. Cancellation/supersession never
erases an in-flight physical outcome. A completed intent is a one-shot goal, not
a permanent controller that fights subsequent panel changes.

`SpaRuntime.request(Control, desired)` is the public intent interface, with
`wait_for_intent` for bounded completion. `CommandEngine` takes explicit monotonic
time and immutable observations, so its safety rules can be tested without I/O.
The internal `Participant` interface carries frames plus opaque receipt tokens;
it is a trusted composition boundary, not an arbitrary-command API for HA.
Transport validates freshness including the **raw stream tail**: garbage after
a parsed CTS invalidates its opportunity even when the parser discards that junk.

Supplemental SETUP/FILTERS/FAULT read queries share CTS arbitration and have bounded
attempts. Missing responses remain `None`, listed in `metadata_failures`; they
never establish invented target limits or "no faults". Known unsolicited typed
metadata updates are observations too. Setup/filter/last fault are refreshed on
epoch or configuration changes, plus received unsolicited updates; regular fault
log polling and full log traversal are future work. The configuration fingerprint
still covers information and capability packets, not mutable schedules/faults.

Target commands use observed setup bounds. Fahrenheit limits are conservatively
rounded inward to 0.5 C steps for Celsius controls, with an additional 10..40 C /
50..104 F supported envelope. Locks/unknown operating modes, hold or priming
inhibit controls. Light 2 is allowed only when both disputed capability bit
locations agree; raw light state 1 remains ambiguous. Pump capability 3 remains
unsupported. Filter scheduling, clock setting and fault clearing are not exposed.

Transactions retain the intent, raw wire frame, epoch, observation sequence,
starting/expected/resulting values, CTS/TX/completion times, result/reason and
latency. Histories are bounded to 100, but active intents are retained separately
so history eviction cannot silently discard another control's goal. Timestamps
are monotonic, not wall-clock dates; an HA adapter may later map them for display.

The interactive tool reads stdin on the main thread while a joined worker owns
the async network loop. It avoids uncancellable executor threads blocked on input.
Shutdown cancels verification waiters, awaits connection cleanup and joins the
worker. CLI physical controls are restricted to numeric loopback addresses;
this is a lab guard, not evidence that the core supports the actual channel bus.
