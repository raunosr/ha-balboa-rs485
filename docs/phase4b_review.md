# Phase 4B review — 0.0.14

## Current status — native acceptance, 2026-09-08

HACS-managed 0.0.14 is now running with the original device and all 54 entities.
The later activation used its separately authorized single HA restart (1/1).
Old installation folders were moved to a recovery archive, not permanently
deleted. Existing settings, identifiers, MQTT entities and automations were retained.

Fresh BWALink-stopped checks preceded activation and native tests. Light OFF/ON/OFF,
Pump 1 OFF/LOW/HIGH/LOW/OFF and Pumps 2/3 ON/OFF passed. The high-to-low test used
the normal intermediate OFF; it did not reproduce controller-forced LOW.
Filter start adjustment passed, but its first restoration was not confirmed and
triggered recovery. Original schedules were subsequently restored and independently
read back. Further hardware tests are paused, with current channel allocation
attempts at 3/3; no runtime reload reset that budget.

The 0.0.15 candidate fixes two independently reproduced readback weaknesses; it
is not yet deployed or hardware accepted. See [filter confirmation review](filter_confirmation_review.md).
Range-aware bathing, remaining advanced controls, natural Cycle 1 evidence and the
long soak remain open. No automation changes or new HA restart were made during
this acceptance/correction turn. The records below are historical checkpoints.

## Historical status — HACS publication, 2026-09-08

The user restored HA independently. Since that report, the public `v0.0.14`
prerelease has been downloaded through HACS; a separate readback confirmed the
installed version. The existing Balboa entry remains disabled and **not_loaded**,
with physical controls disabled. No HA restart or new spa connection was made
during publication. See [publication acceptance](publication_review.md) for public
CI, repository protections and the download check. Hardware acceptance remains
incomplete; do not keep diagnosing the superseded startup outage below or claim
the HACS-downloaded version is currently running.

## Historical acceptance blocker — 2026-09-08 01:05 EEST

The second HA Core restart has not returned a working HA HTTP/MCP connection
after over 13 minutes. This is **not a completed production handover**. The Balboa
entry was disabled before installing 0.0.14 and has not been re-enabled; physical
controls are disabled and no bathing session was started. Original entity IDs,
old MQTT entities and automations are unchanged. Restart allowance is **2/3 used**.

Read-only checks: the HA host answers ICMP, port 22 is reachable, and Observer on
4357 reports Supervisor connected/supported/healthy. This does not establish that
Core is running. Port 8123 at both known HA addresses is unavailable, the browser
terminal's existing ingress session cannot reconnect, and the MCP endpoint is
unreachable. Direct SSH has no previously trusted host key for either the IP or
hostname; no SSH trust check was weakened, no credentials were searched for and
no third blind restart/full-system restore was attempted. The cause of the Core
startup delay is unknown without its startup logs; do not attribute it to the
disabled Balboa integration or to the other agent without evidence.

Resume with Core startup logs or an existing authenticated maintenance connection.
After HA returns: freshly verify BWALink stopped, enable the existing Balboa entry,
verify 0.0.14 and fresh status/metadata, then test Pump 1 observed final-goal
confirmation, reversible filter time edits and range-aware bathing restoration.
Restore original physical settings after each test. Never reset the allocation
budget in a reload loop. Leave real maintenance reminders unacknowledged unless
the maintenance was performed. Keep automation migration deferred.

Last direct passive hardware observation, at spa time 00:42: all raw pumps OFF,
water/target 37 C and heater OFF. This is historical evidence, not a current live
state assertion while HA is unavailable. Light/Pumps 2/3 on/off previously passed;
advanced controls are laboratory-tested but not yet individually hardware accepted.

## Second installation checkpoint

0.0.14 revision `2370c933451ec49e627d8f34f2dae0672218f5cb` passed **610 tests**:
527 core/tools (96.99%), 82 actual HA tests (97.04%), one extracted-ZIP test;
lint, bundle and core/adapter types all passed. Private CI:
[34164326918](https://github.com/raunosr/ha-balboa-rs485-private-archive/actions/runs/34164326918).
Archive SHA-256:
`de5e7d28067a2068b31c2ebcc9b968941110117b976358d1bde399ae820802e5`.
The installer verified all 50 files and retained 0.0.13 at
`/homeassistant/.balboa-backups/0.0.13-xb4jfp6f/balboa_rs485`.
The one-file HA-IP-restricted transfer server closed after delivery. The entry
was verified unloaded and controls disabled before replacement. Second authorized
HA restart requested at 2026-09-07 21:51 UTC: **2/3 used**. Hardware re-test pending.

## Hardware feedback and 0.0.14 correction

0.0.13 loaded after restart, retained all original IDs, and discovered BP6013G2
software 43.0 with 54 entities. Dedicated circulation capability is absent; Pump 1
low provides circulation. Metadata read: Cycle 1 11:00–12:40, Cycle 2 23:00–00:40,
both enabled, 100 minutes each. Historical fault count 11, latest code 19 (priming),
while live Priming was off. Recognized clean-filter reminder remains uncleared.

Seven physical commands passed: light on/off, Pumps 2/3 on/off, Pump 1 low→high.
The Pump 1 high→low request failed confirmation and exhausted the finite allocation
budget during recovery (epoch 4). Status continued fresh; controls were subsequently
disabled during correction. Do not describe this first hardware pass as complete.
The expired channel's old capability/filter data in downloaded diagnostics is not
fresh live metadata. No loop/reload was used to conceal the exhausted limit.

A minimized regression reproduced a concrete command-engine defect: high→low plans
an intermediate OFF, but controller-forced filtration can report LOW directly. The
engine wrongly ignored its already-observed final goal, timed out, and requested a
new connection. It now accepts the post-guard, newer-sequence observed final goal
as well as the expected intermediate value; records the actual resulting value;
and sends no additional toggle. Same-epoch ambiguity, safety, freshness and lost-
confirmation restrictions remain intact. Real TCP tests cover classic/channel modes
with forced LOW and exactly one command/connection. This explains a plausible
cause of the hardware timeout; the intermediate hardware stream was not captured.

Read-only five-second capture of only the existing EW11 connection at spa clock
00:42 showed all pump raw states zero, target/water 37 C, heater OFF. It opened no
new spa socket and sent no command, establishing no pump was left in Jets.

Natural filter boundary was observed without changing schedule or clock: at 00:39,
status flags were 11 (0x0B), Cycle 2 scheduled through 00:40; at 00:40 flags became
3 (0x03). Cycle 1 was scheduled at 11:00. This identifies Cycle 2 mask 0x08 on this
BP6013G2, selecting the pinned Ruby/pybalboa layout. 0.0.14 uses masks 0x04/0x08
only for BP6013G2; Cycle 1 remains explicitly source-inferred, not individually
hardware-proven. Unknown models retain disagreement→unknown. No filter flag is
used as a write-safety guarantee. New redacted passive-pump diagnostics remain
readable when channel control is unavailable.

At this earlier correction checkpoint, 0.0.14 was still being validated and the
restart budget was 1/3 used. The later second-installation/current checkpoints above
supersede that state. Existing automations remain untouched.

## Release installation checkpoint — 2026-09-08

Current candidate `78924bc1c6818f8babbaf8913d9637d12449f72d` passed all **602**
tests: 520 core/tools (96.99% coverage), 81 actual HA 2026.8.3 (97.03%), and one
extracted-ZIP installation test. Ruff, formatting, strict core/adapter types and
byte-equal bundle checks all passed in private CI
[34163062020](https://github.com/raunosr/ha-balboa-rs485-private-archive/actions/runs/34163062020).

Archive `dist/balboa-rs485-0.0.13.zip`: 50 files, 1,459,114 uncompressed bytes,
SHA-256 `fc7e9384127c5aacb084bb2887b65a10f17e755f25437f75389441fe6720a7b8`.
The browser terminal confirmed successful atomic replacement and every installed
file's equality to the archive. Previous 0.0.11 was retained in
`/homeassistant/.balboa-backups/0.0.11-7cxbymnx/balboa_rs485`.
One initial command quoting error failed at Python parse time, before any code or
file change; the corrected command completed. The IP-restricted one-file transfer
server closed immediately after delivery. No public publication or security change.

Before replacement, BWALink was freshly verified stopped/manual boot; the Balboa
entry was disabled and verified unloaded. Physical controls were disabled and no
session was active. Observed state: High target/current 37 C, heater idle, Pump 1
low, Pumps 2/3 off, light off. Old entry and device identities are retained.
HA configuration check was valid. First newly authorized restart requested at
2026-09-07 21:31 UTC: **1/3 used**. Post-restart acceptance is pending below.

Implementation and exact limitations are documented in
`native_controls_0_0_13.md`. The older checkpoints below are historical, not the
current feature inventory or restart count.

## Ongoing completion checkpoint, 2026-09-08

The sections below preserve the first-increment acceptance evidence, not the
current full source inventory. New work remains **not installed**. New restart
allowance is still **0/3 used**. Old automations/MQTT entities are untouched.

- RangeSession v2 persists High capture, per-field restoration ownership, original
  range/mode/target, operation identity and deadline; legacy v1 remains readable.
  Tests cover all nine crash/write boundaries, expiry-first recovery, full storage,
  manual/external edits and disabled controls. Target minimum is 36.5 C; higher
  High targets are not lowered. Fahrenheit minimum is rounded upward.
- Native start/end/+30/-30 buttons and HA-owned duration/minimum preferences passed
  real HA reload/round-trip tests. Explicit abandon requires confirmation and sends
  no spa command. Sensor/download diagnostics expose transaction/restoration state.
- Four filter time entities, duration sensors and Cycle 2 switch passed actual HA
  tests. Core uses fresh read/modify/write/readback, preserves the other cycle,
  serializes edits, rejects stale reads and never replays after reconnect.
- Clock and unit native controls passed actual HA tests; unit changes are blocked
  during sessions. Format preference does not rewrite time. Clock writes do not
  survive a connection epoch. Core maintenance and safety tests passed; HA bindings
  are being validated next, alongside remaining metadata observations.
- Most recent full local suite: 505 passed, 97.01% branch coverage. Real HA tests at
  revision `7a05a76` had 79 pass and one expected missing-maintenance-UI test fail;
  do not treat this development checkpoint as release acceptance.
- Read-only production check at 2026-09-07 20:41 UTC: BWALink stopped, current native
  runtime READY, channel 27, epoch 2, allocations 2/3, one recovery, CRC 104. Status
  age 0.046 s. No new socket, physical command or restart was used for this check.

Remaining gate: finish observations/maintenance UI, full green CI/types/package,
review and safe production installation/acceptance. Unresolved filter-bit layout
must remain explicit rather than inventing values; finite allocation-budget long
soak remains outside a short entity acceptance test.

Status: first increment laboratory checks passed; **not installed**. Phase 4B as a whole
remains open. Production is still the accepted 0.0.11 from Phase 6.

## Changes and evidence

- Native read-only water, heater, mode/range, reminder, clock, Hold/Priming and
  lock observations. Unknown heater flags remain unknown; waiting is not heating.
- Fresh passive readings do not require channel ownership; stale/absent status
  invalidates them even if other valid traffic continues. No added sensor TX.
- Controller model/software from BF24 populate HA Device info after discovery;
  no BWA Link version is reused as firmware. Four low-noise diagnostic entities
  expose channel, CRC errors, recoveries and remaining allocation attempts.
- Named Pump 1 select preserves its fan identity and shares observed command
  verification. Capabilities determine two-speed or single-speed choices.
- Climate Low/High presets use independently stored spa targets without changing
  Ready/Rest. The simulator now models independent targets instead of clamping
  a single shared target when changing ranges.
- A separate Ready/Rest policy select never offers the transient Ready-in-Rest as
  a requested target, and does not change the temperature range or setpoint.
- Manual session-related settings are serialized with session creation through
  storage and command completion. A legacy active/restoring session blocks range
  and mode changes. Explicit manual targets retain durable-abandon semantics.
- No new bus opcode, transport timing, retry budget or safety-bit bypass.
  No production connection, physical command, installation or restart this turn.

Protocol observations follow the pinned source review and existing decoding.
The native presentation follows the official HA
[binary sensor](https://developers.home-assistant.io/docs/core/entity/binary-sensor/),
[select](https://developers.home-assistant.io/docs/core/entity/select/) and
[climate](https://developers.home-assistant.io/docs/core/entity/climate/) contracts.
In particular, lock indicators do not use HA's LOCK class (ON would mean unlocked),
and manual pump speeds are not misrepresented as fan presets.

## Test discipline and review findings

Each new vertical slice started with a failing core or actual-HA test. The first
water-sensor test failed because the entity did not exist; the implemented sensor
then passed stale/recovery and zero-TX checks in real HA 2026.8.3. The safety suite
subsequently passed with the same passive/stale contract. Core tests cover invalid
clock bytes, known/unknown reminder codes and independent range targets.

One diagnostic test incorrectly equated classic fixed address 10 with a negotiated
channel. The minimized failure was `unknown != 10`; Snapshot reads the channel
negotiator, which is intentionally unused in classic mode. The test now covers
both classic unknown and an actual simulator-assigned channel 18. The production
logic was not weakened to satisfy a wrong expectation. No debug logging remains.

The manual/session race tests cover both arrival orders: a pending session save
blocks/refuses a range change, and a pending range write makes the later session
validate against the newly observed range. Invalid manual targets and disabled
controls cannot discard an existing session. Original session storage and expiry
semantics remain unchanged; no storage schema migration is introduced.

## Remaining gates

- All 477 tests passed: 401 core/tools (97.73% branch coverage), 75 actual HA
  2026.8.3 tests (97.67%), and one extracted-ZIP installation test. Lint, strict
  core/adapter types and byte-equal bundle checks passed in private CI
  [34158381651](https://github.com/raunosr/ha-balboa-rs485-private-archive/actions/runs/34158381651),
  revision `3bcb7c9558792fffffa73973da03e53e97db6177`.
- `dist/balboa-rs485-0.0.12.zip`: 45 files, 1,244,736 bytes, SHA-256
  `3b335f3da609fd23faf03f276024a36c0fe0dacc58b11a1b2edda85b83b26ba3`.
- The user subsequently requested all remaining supported features and installation,
  granting a **new three-restart allowance** on 2026-09-07. Used: **0/3**.
  Earlier grants were exhausted and do not add to this new allowance. Verify
  BWALink is still stopped before any future connection or command testing.
- Range-aware bathing session (minimum 36.5 C, original High capture and restoration
  after every crash boundary), filter schedules/running evidence, clock/unit writes,
  circulation capability evidence and advanced actions remain later increments.
- Existing finite channel-allocation budget / weak-WLAN long soak remains open.
  More entity coverage does not establish unattended reliability.

EW11 settings are documented in `ew11_settings.md`, including 115200/8N1,
half-duplex, TCP server 8899 and the tested 10 ms Gap Time. They were not changed.

## Current execution authority

The user is away/asleep and requested autonomous completion and HA deployment.
Do not alter/delete existing MQTT entities or automations: automation migration
and cleanup are explicitly postponed until after the new integration is running.
Keep BWALink stopped; verify its current state before hardware testing. Prepare
the remaining range-aware/filter/control work in the laboratory before spending
the new restart budget. No new production restart has occurred in this turn.
