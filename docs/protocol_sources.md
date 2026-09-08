# Protocol source ledger

Reviewed 2026-09-05. These are reverse-engineered community references, not a
vendor protocol guarantee. A short passive Elfin observation is recorded in
`hardware_validation.md`; it does not validate configuration or control writes.
Evidence order: captured traffic, agreeing implementations, protocol docs, isolated
implementation. Independent means separate code, not proof of independent discovery.

## Pinned repositories and reuse decisions

| Reference | Reviewed revision | License evidence | Reuse |
| --- | --- | --- | --- |
| [ccutrer/balboa_worldwide_app](https://github.com/ccutrer/balboa_worldwide_app/tree/a9031c7c4b3060ecb093f1c74ee42b45ef89934c) | a9031c7c4b3060ecb093f1c74ee42b45ef89934c | gemspec declares MIT; no LICENSE file in snapshot | Protocol facts and behavioral reference only; no code copied |
| [garbled1/pybalboa](https://github.com/garbled1/pybalboa/tree/845c0c65f367d434be042f9683a1a4f19ffdd0ac) | 845c0c65f367d434be042f9683a1a4f19ffdd0ac | LICENSE is Apache-2.0 | Independent implementation; two factual checksum vectors credited |
| [jshank/bwalink](https://github.com/jshank/bwalink/tree/bab3dea3a667908a691326976c60522824c00efb) | bab3dea3a667908a691326976c60522824c00efb | No root license found | Topology/setup research only; no code/text copied |
| [paw2paw/balboa_robust](https://github.com/paw2paw/balboa_robust/tree/a20f2318d64a56da237811f52edebed886b9d374) | a20f2318d64a56da237811f52edebed886b9d374 | MIT, Paul Wander 2026 | Reliability design reference only |
| [Home Assistant core](https://github.com/home-assistant/core/tree/93ecba49bd35ee65d12596d3d7f28863a63dd8fe/homeassistant/components/balboa) | 93ecba49bd35ee65d12596d3d7f28863a63dd8fe | LICENSE.md Apache-2.0 | Lifecycle/entity reference only, no adapter in Phase 1 |
| [HyperActiveJ channel reference](https://github.com/HyperActiveJ/sundance780-jacuzzi-balboa-rs485-tcp/tree/fc38ab5e593b963502b76d508d573c3394286874) | fc38ab5e593b963502b76d508d573c3394286874 | setup.py declares Apache 2.0 | Channel architecture research only; no code copied |

Do not rely on balboa_robust's README calling pybalboa MIT: the inspected pybalboa
LICENSE is Apache-2.0. Re-check license and preserve notices before any later source
reuse. This private project has not yet selected a distribution license.

## Features and verification

Simulator/test column describes Phase 1 coverage; actual test results are recorded
in `phase1_review.md`. All hardware validation is pending.

| Feature | Primary location | Confirming source | Lab/test scope | Hardware |
| --- | --- | --- | --- | --- |
| CRC-8 07/init02/xor02 | Ruby lib/bwa/crc.rb, message.rb | Python utils.calculate_checksum, tests/test_utils.py | Fixed external vectors, data corruption, independent comparison | Pending |
| Frame envelope / length | Ruby message.rb, doc/protocol.md | Python utils.read_one_message, client.send_message | All splits, coalescing, garbage, lengths, CRC, terminator, reset | Pending |
| READY `10 bf 06` | Ruby doc/protocol.md#ready, messages/ready.rb, client.poll | pybalboa #53/#55 discussion; channel implementation uses addressed CTS | Exact signature + no payload; display only | Pending; classic applicability unproven |
| Status `ff af 13` | Ruby messages/status.rb | Python client._parse_status_update/enums | Common fields, 23..32 payload bytes, immutable raw extensions | Pending |
| Celsius / missing temperature | Ruby status.rb | Python client status parser | Half degrees, Fahrenheit, ff current sentinel | Pending |
| Heat mode/state | Ruby status.rb | Python enums.py and status parser | Preserve raw bits; mode2, state2 waiting | Pending |
| Pump slots | Ruby status.rb | Python status parser, Ruby issue #53 | Six raw pump slots; no speed/capability inference | Pending |
| Lights / circulation | Ruby status.rb | Python status parser (light semantics differ) | Raw two-bit lights, circulation bit | Pending |
| Absolute target `bf20` | Ruby set_target_temperature.rb | Python client.set_temperature | Research only; command deferred | Pending |
| Toggle `bf11` | Ruby toggle_item.rb/client.rb | Python control.py/enums.py | Research only; lost-confirmation invariant in Phase 3 | Pending |
| Control config `bf2e` | Ruby control_configuration.rb | Python _parse_device_configuration | Research only, deferred Phase 2 | Pending |
| Model/signature `bf24` | Ruby doc/protocol.md / control_configuration.rb | Python _parse_system_information | Research only, deferred Phase 2 | Pending |
| Filters `bf23` | Ruby filter_cycles.rb | Python _parse_filter_cycle | Research only, deferred | Pending |
| Fault log `bf28` | Ruby doc/protocol.md (not error.rb, which is bfe1) | Python _parse_fault_log/control.py; HA event.py | Research only, deferred | Pending |
| Channel assignment | pybalboa #11 and linked Sundance implementation | #11 credits bggardner/pybalboa clients.py | Architecture only; full header retained | Pending |
| Elfin raw TCP | BWALink README | Ruby #73; pybalboa #55 | Configurable TCP port, loopback only | Pending |
| Zombie/reconnect | pybalboa #110, balboa_robust connection.py | Python listener/availability inspection | Timeout/EOF only now; state machine Phase 2 | Pending |

## Specific findings and disagreements

- Ruby serial/RFC2217/ESPHome paths initialize a queue; `send_message` enqueues,
  and `poll` shifts one message on READY. Ruby `tcp://` bypasses that queue.
  Do not copy scheme-based scheduling to an Elfin raw TCP bridge.
- Python's listener can repeatedly attempt a keepalive after silence without
  forcing a new socket; robust wraps lifecycle with data/config and health gates.
  Phase 2 must track valid traffic with monotonic time and explicitly close sockets.
- Ruby documentation says ready-in-rest is 3; both current enum/implementation
  paths use 2. Decode 2, preserve 3 as unknown. Ruby's boolean heating treats
  both 1 and 2 as active; Python distinguishes heating (1) from waiting (2).
- Ruby accepts 23..32-byte status payloads; Python documents 24. Decode only
  common fields through byte 20 and retain remaining bytes without guessing.
- Ruby light decoding treats any nonzero two-bit state as on; Python uses the
  high bit. Retain raw two-bit values in this phase.
- Configuration tables differ on extra pumps, lights, and blower bits. Do not
  extrapolate accessories from zero status slots. Capabilities require config.
- CRC implementations look different: direct register init02 versus augmented
  initB5 plus eight trailing steps. Compare outputs before treating as a conflict.
- Frame bound 125 follows Ruby and is a supported lab policy, not proof that no
  larger Balboa message exists. Document and test bounds before widening.

CRC comparison completed: all 5,257 cases agreed (empty input, all 256 single
octets, 5,000 seeded random byte strings of lengths 0..124). The one-off check
evaluated only the upstream checksum function from the pinned source; it is not
a runtime dependency or a requirement for the offline test suite. The resulting
classic READY wire vector is `7e 05 10 bf 06 5c 7e`.

## Failure-case corpus reviewed

| Issue | Observation | Consequence |
| --- | --- | --- |
| [pybalboa #53](https://github.com/garbled1/pybalboa/issues/53) | Physical RS485 requires addressed CTS; Wi-Fi module normally handles it | Separate bus policy from TCP |
| [pybalboa #55](https://github.com/garbled1/pybalboa/issues/55) | EW11 native HA config failed; Ruby path worked for reporter | Avoid Wi-Fi-only config requirements |
| [pybalboa #110](https://github.com/garbled1/pybalboa/issues/110) | Silent socket without FIN/RST; downstream reports include incomplete recovery | Deadlines + hard close; no assumption that wrapper fixes all devices |
| [pybalboa #11](https://github.com/garbled1/pybalboa/issues/11) | Channel 00..07 negotiation, alternative C4/CA/CC status/control family | Keep header/address; unknown read-only; no automatic alternative writes |
| [Ruby #75](https://github.com/ccutrer/balboa_worldwide_app/issues/75) | Rapid/first commands followed by reset and loss | Physical transactions must be epoch-scoped |
| [Ruby #53](https://github.com/ccutrer/balboa_worldwide_app/issues/53) | Single-speed pump reported 2; modulo calculation sent zero toggles for off | Capability-aware state mapping before action |
| [Ruby #70](https://github.com/ccutrer/balboa_worldwide_app/issues/70) | Boolean/speed mismatch crashed pump operation | Typed intent validation |
| [Ruby #65](https://github.com/ccutrer/balboa_worldwide_app/issues/65) | Unavailability mixed with MQTT/VM/time behavior, cause uncertain | Distinct health counters and monotonic deadlines |
| [Ruby #73](https://github.com/ccutrer/balboa_worldwide_app/issues/73) | Elfin at port 9999; socat/RFC2217 trouble; direct TCP success report | Configurable port, raw bridge, anecdote not bus-safety proof |
| [Ruby #19](https://github.com/ccutrer/balboa_worldwide_app/issues/19) | Concurrent app/client connections sometimes timed out | Single runtime connection, concurrency tests later |
| [Ruby #92](https://github.com/ccutrer/balboa_worldwide_app/issues/92) | Fault visibility and clear notification confused; range regression also reported | Separate fault log, clear intent, configuration ranges |

HA review included __init__, config/options flow, base entity/device identity,
climate/fan/light/select/switch/time/event mappings, strings, and component tests.
This pinned component has no diagnostics.py or checked-in translations directory;
those remain explicit new adapter requirements rather than claimed reused features.

## Phase 2 implementation evidence

- BF22 information request `02 00 00` and capabilities request `00 00 01`:
  Ruby `control_configuration_request.rb` and Python request methods agree.
  Implemented independently; loopback CTS-gated sync, timeout and retry tests.
- BF24: exact 21-byte response; common model, version, setup and raw signature
  from Ruby protocol docs and Python system-information parser. Non-ASCII model
  bytes remain preserved in the raw immutable frame; display uses replacement.
- BF2E: exact six-byte response. Agreed pump descriptors: four pairs in byte 0,
  pump 5 byte 1 low pair, pump 6 byte 1 high pair. Disputed accessories remain raw.
- Configuration fingerprint includes all 27 raw response bytes with versioned
  SHA-256, not just model. Replies have no transaction identifier; correlation is
  limited to expected response type in the current socket epoch. A pair of replies
  is not an atomic controller snapshot. Refresh periodically; do not claim otherwise.
- Hardware observed addressed CTS/no-message `11 BF06/07` interleaved with
  `10 BF06`. Conservative channel veto and auto read-only behavior were verified.
  No query, negotiation or control write has been hardware-validated.

## Phase 3 source decisions and coverage

Known BF11 item codes and BF20 target encoding were independently implemented
from pinned Ruby `toggle_item.rb` / `set_target_temperature.rb` and Python
`ToggleItemCode` / `set_temperature`. No source code was copied. Query SETUP
`04 00 00`, FILTERS `01 00 00`, last FAULT `20 ff 00`, and response lengths 9/8/10
follow Ruby protocol/messages and Python request/parser methods. The original
nine-byte-only SETUP decision was incomplete: the wiki also documents ten-byte
payloads with identical common bound positions. The BP6013G2 hardware capture
confirmed the ten-byte variant; 0.0.9 accepts exactly 9/10 and retains the extra
byte without interpreting it. Raw frames remain
attached to typed observations, including unknown fault codes.

State mapping now covers agreed pumps, first blower, aux 1/2, first mister,
unambiguous lights, heat mode/range and supplemental observations. Ruby/Python
agree on status blower byte 13 bits 2..3, mister byte 15 bit 0, aux bits 3/4.
Capability restrictions are documented in `phase3_design.md`; disagreements are
not resolved by guessing. The single-speed pump raw-2 behavior from Ruby #53 is
protected by real TCP ON/OFF tests. Ready-in-rest transitions first to REST before
READY, matching the Python implementation and checked with a pure engine test.

The no-blind-toggle-retry architecture is new, not copied from the upstream
precomputed-toggle loops. Mandatory real TCP tests apply a toggle, drop status,
force confirmation timeout, resynchronize and assert one total toggle for desired
LOW or a second toggle only from newly observed LOW for desired HIGH. Abrupt
disconnect, stale observations, coalescing, history eviction, cancellation,
capability removal and bounded physical-action budgets are also tested.

All Phase 3 physical commands remain **hardware pending**. The user's Elfin
observation contains channel traffic; no negotiation/ownership implementation or
real-spa write validation has been added in this phase.

## Phase 4 channel prerequisite

Additional fact-only reference: [bggardner/pybalboa](https://github.com/bggardner/pybalboa/tree/f515a28bf9441292f7a8e792a09b3b4e2f069b5b),
Apache-2.0 LICENSE inspected, `messages.py` and `clients.py`. No source copied.
The [protocol wiki](https://github.com/ccutrer/balboa_worldwide_app/wiki#channel-assignment-request)
contains request/reply examples: FE BF00 invitation, FE BF01 request with
device byte 02 and two correlation bytes, FE BF02 assignment, addressed BF03 ACK.
CTS addresses 10..2F are supported; 30..3F are reported not to receive CTS.
Some examples change correlation bytes: this implementation deliberately rejects
those replies rather than assuming ownership. It never adopts an unused-looking
address. The source's fixed F173 identity and unchecked responses are not reused.

Own-channel BF04 receives the documented BF05 payload 04 08 00. Idle owned CTS
gets BF07. Standard BF22/BF11/BF20 traffic is addressed to the negotiated channel;
responses retain that raw address. Alternative encrypted families remain blocked.
Observed client traffic on the owned address revokes permission (collision or
gateway echo cannot be distinguished). One assignment request per socket, at most
three per runtime, limits channel-allocation exhaustion. This is a conservative
supported subset, not a proof of compatibility with all firmware or TCP latency.

[NorthernMan54/esp32_balboa_spa](https://github.com/NorthernMan54/esp32_balboa_spa/tree/49253f8681e7ba8c4dde265aa7a0ee73fd3ae46e)
was inspected for comparison only: its active fixed Wi-Fi address and different
BF05 descriptor are not adopted. No code/assets copied. All new physical controls
remain simulator-only until separately coordinated hardware validation.

The protocol wiki's Status Update flags byte 21 bit 3 reports a settings lock
(or temperature-limit test mode). Phase 4 additionally inhibits all physical
controls when that bit is present. The existing operating-mode/panel-bit guard
remains conservative. A regression test verifies rejection; no unlock message
is implemented or sent. Conflicting filter-running bit assignments in community
references remain unresolved and must not be used as a write-safety guarantee.

0.0.9 additionally recognizes the observed clean-filter reminder for control
admission: normal operating state, initialization 3, reminder type 4, notification
byte 18 exactly 1, no lock/unknown high flags. This matches the wiki's documented
reminder fields. No reminder is cleared; faults, other reminders and all existing
locking/availability guards remain conservative. See `bp6013_compatibility_review.md`.

## 0.0.7 bounded ACK recovery

Rechecked the wiki's assignment and CTS descriptions on 2026-09-07. A correlated
offer may be retained without granting ownership; if its immediate slot is lost,
a fresh CTS for that explicitly offered address can carry the one known BF03 ACK
within the existing deadline. This is an inference from the documented addressed
CTS permission, not proof every firmware polls before ACK. No CTS means no TX.
See `channel_ack_review.md` for the pre-fix TCP reproduction, hardware evidence,
limits, and distinction between confirmed behavior and the historical HA failure.

The subsequent 0.0.7 production capture confirmed a correlated offer coalesced with
another client's CTS/NTS and no CTS on the offered address. Deferred ACK therefore
cannot recover this observed controller. 0.0.8 retains bus freshness checks and
instead retries handshake via a new socket/nonce with existing backoff and the
unchanged three-request lifetime budget. See the current review for measured data.

## Phase 4B additions, 2026-09-08

Independent implementations from facts, not copied upstream code:

- BF23 filters follow pinned Ruby `filter_cycles.rb`, pybalboa and the wiki.
  Read before modification and explicitly query after sending: the write has no
  acknowledgement. Preserve the untouched cycle, serialize edits, cancel across
  a new socket epoch. A reflected write is not a queried confirmation. Equal
  start/end is rejected rather than choosing zero versus 24 hours implicitly.
- BF21 clock encodes hour (24-hour flag in bit 7) and minute. BF27 preference 01
  changes unit (0 F / 1 C). Display format uses the wiki's explicit BF27 preference
  02 (0 12-hour / 1 24-hour), not an upstream convenience setter that rewrites time.
  Status confirms results; hardware acceptance remains pending at this checkpoint.
- BF11 item 3C Hold, 01 Normal Operation, 1D all-pumps-off Soak and 03 reminder
  acknowledge follow the pinned item tables and wiki. Normal Operation only exits
  known Hold: never Priming, test or fault states. Only reminder codes 04/09/0A with
  known reminder flags may be acknowledged; fault history is never cleared.
- Maintenance admission is per control. Hold permits only Hold/Normal exit, not
  general pump/heating writes. Existing locks/unsafe flags remain barriers. Unit
  and maintenance changes are serialized with sessions; explicit Hold exit can
  unblock restoration after an external panel change. Soak confirms supported
  pumps off, does not promise to stop dedicated or controller-forced circulation.

Primary reference: [protocol wiki](https://github.com/ccutrer/balboa_worldwide_app/wiki),
re-read 2026-09-08. Its filter mode bits 3/4 still conflict with Ruby/pybalboa bits
2/3. The old physical capture only had byte 9 = 3 (both layouts agree: no filter),
so it cannot settle the disagreement. Never use an uncertain filter indication as
a write-safety guarantee. Historical fault codes are not active alarms or current
sensor-A/B temperature measurements.

### BP6013G2 natural filter boundary, 2026-09-08

At spa clock 00:39 the observed flags were 0x0B; at 00:40 they became 0x03,
matching the unchanged Cycle 2 schedule 23:00 + 100 minutes. Cycle 1's schedule
was 11:00 + 100 minutes. Thus Cycle 2 mask 0x08 is supported on this controller,
selecting the pinned Ruby/pybalboa layout over the wiki's bit-offset description.
The 0x04 Cycle 1 mapping is inferred from those sources, not independently observed
at its transition. 0.0.14 scopes this layout to BP6013G2; other models keep the
conservative source-consensus interpretation. No clock/schedule changes forced
this observation. The mapping is diagnostic, never a safety guard.
