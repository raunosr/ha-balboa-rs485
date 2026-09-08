# BP6013G2 control admission and SETUP variant — 0.0.9 candidate

## Physical command/session acceptance completed

HA 2026.8.3 RUNNING verified at 18:05:01 UTC. Initial negotiation exhausted three
attempts; one user-authorized integration-only reload reached READY, channel 23,
epoch 1. All metadata including SETUP parsed successfully; target limits 27..40 C.

The 37 -> 36.5 C test sent an absolute target but initially timed out after 4.016 s.
After resynchronization and fresh observed 37 C, the desired-state engine sent the
absolute goal in epoch 3/channel 24, verified in 0.248 s. Returning to 37 C verified
in 0.271 s. This is observed recovery, not a blind toggle replay or first-try success.

A 120-second heating session (target 37 C, maintenance 36.5 C) was started. During
it, Balboa alone was disabled/enabled. The new owner reached READY on channel 25,
epoch 1, and restored the exact original end time `2026-09-07T18:10:58.497684+00:00`.
It reached holding from observed temperature. Expiry sent and verified maintenance
36.5 C in 0.525 s and returned to idle. The original target 37 C was then restored
and observed; physical controls disabled through options. Final check 18:11:41 UTC:
water 37 C, target 37 C, heater OFF, session idle.

Short physical target/session and integration-unload persistence tests passed.
An active-session full Core reboot was not injected; that path remains laboratory
tested. No pumps/lights, forced network faults or additional Core restarts were
used. The long-duration allocation-budget limitation below and remaining native
entity parity are open final-acceptance work. These short tests do not certify a
72-hour soak. Phase 6 may now proceed under the user's authorization (0/2 Phase-6
Core restarts used).

## Latest deployment checkpoint (2026-09-07 evening)

The user explicitly approved installing 0.0.9 and one additional HA Core restart.
Before installation, BWALink was verified stopped and the session was idle.
The earlier 0.0.8 runtime had since lost ownership: epoch 5, three allocation
requests exhausted, four recoveries, fresh read-only status but no control
availability. RX 1,957,108 / CRC 455 / invalid 257. The precise intervening loss
cause was not captured. This is an unresolved long-duration recovery limitation,
not proof that the earlier successful handshake stayed healthy indefinitely.

Only Balboa was disabled/unloaded. The 0.0.9 archive below was hash-verified and
all 41 installed files checked byte-for-byte. Previous 0.0.8 is retained under
`/config/.balboa-backups/`. The one-artifact transfer endpoint closed after delivery.
The separately authorized additional restart was requested successfully at
**18:00:21 UTC**. Startup and physical acceptance are pending. Correction restart
budgets now exhausted (original 2 plus explicitly approved extra 1); conditional
Phase-6 budget remains 0/2. The sections below preserve the pre-install review.

## Evidence (2026-09-07)

Installed 0.0.8 reached READY through its bounded channel-recovery mechanism.
HA climate calls requesting 36.5 C failed before transmission, with
`Controls require a fresh synchronized normal operating state`. History contained
zero physical commands; the observed target stayed 37 C and session stayed idle.
The first MCP options/service attempt had an unstructured error response; readback
confirmed options had changed but no command had been sent. A second explicit
service call returned HTTP 500; HA logs identified the admission error. Do not
interpret an API error as a sent or verified physical command.

Offline analysis of the earlier successful-channel capture found constant status
fields: operating 0, initialization 3, reminder type 4, byte 9 = 3, notification
byte 18 = 1, byte 19 = 32, lock byte 21 = 0. These represent a clean-filter
reminder, not priming/hold. Its SETUP response was ten payload bytes; valid common
temperature bounds were 50..99 F and 80..104 F. No new live socket or raw command
was used for this analysis. Captures stay private and outside version control.

The [protocol wiki](https://github.com/ccutrer/balboa_worldwide_app/wiki#status-update)
documents reminder initialization value 3, clean-filter type 4, and notification
bit 0. Its [SETUP examples](https://github.com/ccutrer/balboa_worldwide_app/wiki#settings-0x04-response)
include both nine- and ten-byte payloads. The original strict nine-byte parser
and idle-only admission did not support these variants.

## Minimal change and safety review

- Decode exactly 9 or 10 SETUP bytes, preserving opaque bytes in the frame.
  Read only the previously agreed bound positions; reject missing, reversed,
  zero and 255 sentinel bounds as before. Never substitute invented target limits.
- Admit the specifically identified clean-filter reminder only when operating
  state is normal, initialization is 3, reminder type is 4 and notification byte
  is exactly 1. All availability, priming/hold, lock and unknown-state guards remain.
  Other reminders remain conservative/unsupported. No reminder-clear message is
  generated, and the reminder remains present after the simulated commands.
- No transport timing, retry budget, raw-toggle policy or persistence change.

Three new checks failed on 0.0.8 before implementation. The candidate passes the
same tests plus a real-TCP channel test that verifies target change and restoration
with the reminder and extended SETUP present. An actual-HA service regression
uses the same synthetic variant. Raw capture payloads are not test fixtures.

## Deployment gate

0.0.9 is **local, not installed**. All 363 local core tests passed (97.54%
coverage), plus formatting, lint, strict typing and generated-core equality.
Private [CI 34101021761](https://github.com/raunosr/ha-balboa-rs485/actions/runs/34101021761)
passed: 363 core tests (97.54%), 51 actual HA 2026.8.3 tests (97.19%), one isolated
ZIP installation test, formatting/lint/typing/bundle checks. **415 tests passed**.
The additional HA case uses channel negotiation, the reminder status and ten-byte
SETUP, and confirms the service only returns after the simulated target changes.
Candidate commit: `c2000497b52b8f92e70006f0738cc0195e2983a4`.
Candidate ZIP SHA-256:
`b0a06d4720d12f5b567ea83da94706befc6ce7c62a4d23ff9679af108c1054b3`.
Production remains 0.0.8, loaded with controls disabled, target observed 37 C,
session idle. No physical spa commands have been transmitted.

At 08:31:37 UTC, production was still READY in epoch 3 on channel 22, with no
additional recoveries, controls disabled, water/target 37 C and session idle.
RX 38,913 / CRC 33 / invalid messages 12; SETUP remained the metadata failure.
These link/parser errors are disclosed, not considered a passed long-duration
soak or proof of their physical cause. No extra reload or restart was requested.

Current-correction HA Core restart budget is exhausted (2/2). The user's separate
two-restart allowance for Phase 6 applies only after this acceptance gate passes.
Do not use it for this candidate. All checks passed; production installation and
one additional Core restart await explicit permission. Retain the previous
directory on installation. Phase 6 has not started, because actual physical
target/session acceptance is still pending.
