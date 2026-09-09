# Filter confirmation review — 0.0.15

Status updated 2026-09-08: 0.0.15 installed through HACS; bounded filter correction
hardware retest passed. Remaining native-control/recovery acceptance is incomplete.
Automation migration/cleanup is explicitly deferred. No new HA restart authority
is available; the later HACS activation used its one permitted restart. The
candidate-era sections below are retained as the original development record.

## Installed 0.0.15 acceptance update

Release validation completed: 548 core/tool tests, 84 actual-HA tests and one
isolated ZIP installation test passed (633 total), with lint, formatting, typing
and HACS validation. HACS activation used its authorized single Core restart.

Native Cycle 1 start change and explicit restoration were independently VERIFIED
at 2.617690s and 0.422906s. Duration and Cycle 2 were preserved; independent entity
readback confirmed both original schedules. No extra reconnect was used during
these two writes. This closes the bounded filter retest only.

Start/Extend/Reduce/End on an already-suitable High target passed without physical
writes. A later High-to-Low change verified, but bathing Low-to-High timed out
and channel recovery failed. The test session was abandoned and controls disabled;
the user then restored High with BWALink and stopped it. No automation was changed.
For current recovery findings and the next bounded step, see
`bwalink_transport_review.md`. Do not repeat the historical filter installation
gate below or count this as all-native/long-soak acceptance.

## Production evidence on 0.0.14

After HACS activation, all 54 native entities and diagnostics were present. BWALink
was freshly confirmed stopped before bounded control tests. Pump 1 OFF → LOW →
HIGH → LOW → OFF and Pumps 2/3 ON → OFF passed (eight requested changes, ten
verified physical steps). Pump 1 HIGH → LOW traversed OFF normally: this is not
new physical proof of the forced-circulation shortcut. All pumps were restored OFF,
water/High target remained 37 C, and no bathing session was started.

A one-minute Cycle 1 start change was confirmed. Its first restoration timed out
at 4.013 seconds, and the runtime recovered twice. The returned schedule still
showed the changed start. Subsequent freshly observed, explicitly requested edits
restored the original schedule; final readback confirmed both original start/end
times and durations, with the untouched Cycle 2 retained. No blind whole-record
write replay, HA restart or integration reload was used to hide the failure.

The MCP service envelope reported success despite the mismatching observed value;
only independent state and transaction diagnostics were accepted as evidence.
Further physical tests stopped after restoration. The live runtime was READY on
its third allocated channel (attempts 3/3), with two recoveries and CRC errors.
An additional reconnect can therefore leave physical controls unavailable.

## Reproducers and competing explanations

Two failures were independently reproduced on loopback TCP before their fixes:

1. An early queried filter response contains the previous schedule. The existing
   implementation stopped reading after that response and waited for a timeout,
   even when a second query would return the committed value. Both classic and
   assigned-channel modes reproduced the failure.
2. Drop the first two post-write filter responses with the production query
   timeout of two seconds. The four-second physical confirmation timeout expired
   before the third permitted query could complete.

These explain concrete robustness defects, **not the proven cause of the original
hardware failure**. A write lost on the serial bus or ignored by the controller
also fits the observed old schedule. Without an intermediate traffic capture the
live event cannot distinguish those possibilities. Increasing read tolerance does
not make a lost physical write succeed.

## Scoped correction and invariants

- Mismatching post-write queried responses keep the readback request active.
  Only the known read query is sent, once per fresh owned bus opportunity.
- Mismatches and missing replies share the existing three-query maximum; neither
  starts an unbounded loop or resets the physical confirmation deadline.
- The default runtime gives filter confirmation a deadline of
  `max(4, query_timeout * query_attempts + degrade_after)` seconds: nine with the
  current policy. The last term allows bounded bus/observation slack. An explicitly
  injected test engine retains its own timing policy.
- Pump/toggle confirmation remains four seconds. Staleness, locks, epoch changes,
  no-optimism checks and the finite channel-allocation budget are unchanged.
- The immutable pending transaction exposes readback context, not a raw-command
  retry interface. Configuration/state remain owned by their existing layers.
- Persistent mismatch still fails. No second physical filter write is sent, and
  an ambiguous write is never replayed after reconnect. Hardware admission and
  same-epoch correlation limitations are not weakened.

## Validation and next gate

Regression coverage includes one/two old replies, one/two lost replies, mixed
loss/mismatch, exhausted read budgets and no duplicate write, in classic/channel
TCP modes. A default-runtime timing regression and pump-timeout isolation cover
the separate deadline. Actual-HA service tests cover successful native time edits
and a propagated HomeAssistantError on exhausted confirmation.

Local full suite: **548 tests passed**, 97.01% branch coverage; Ruff lint/format,
strict core typing and bundled-core equality passed. Actual-HA CI results will
be recorded before release. No temporary production instrumentation was installed.
The private minimal probe was removed after its permanent regressions passed.

Next gate: reviewed HACS update with a newly authorized HA restart, read-only
preflight, then one reversible filter change and restoration with diagnostic
verification after each call. Only then continue remaining native-control/bathing
acceptance. Natural Cycle 1 evidence, other advanced controls and long-duration
weak-network acceptance remain open. Old automations stay untouched.
