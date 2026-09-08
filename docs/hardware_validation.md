# Hardware validation — dated acceptance evidence

## 2026-09-07 19:12 UTC: 0.0.11 prediction acceptance complete

Forecast/model sensors and the corrected options form passed bounded production
acceptance. HA remains 2026.8.3; both Phase-6 Core restarts are used. Water and
target remain 37 C, session idle, physical controls disabled, BWALink stopped.
READY followed one automatic recovery (epoch 2, channel 27, two assignment
requests); no physical spa command was sent in Phase 6. Options rate 2 -> 2.5 -> 2
was verified without reconnecting. Version 0.0.11 and 12 entities were confirmed
in the browser. Full evidence and the final 455-test CI are in `phase6_review.md`.
Prediction is initially learning, not yet measured against this spa's heating.
Long-duration channel-budget recovery and full native entity parity remain open.

## 2026-09-07 evening: 0.0.9 short physical acceptance passed

Installed 0.0.9 passed absolute target 37 -> 36.5 -> 37 C and a 120-second
heating session with a Balboa-only reload while active. The original deadline
survived reload; expiry restored 36.5 C automatically and was observed verified.
Target was then restored to 37 C, session idle, physical controls disabled.
The initial target write did time out and required resynchronization before the
absolute goal was verified. This was not an all-first-try command success.
See `bp6013_compatibility_review.md` for timestamps and measured latencies.

This passed the short Phase-5 gate and Phase 6 proceeded. It does not close the
long-duration three-allocation-request limit: an evening 0.0.8 observation had
exhausted that budget after earlier successful operation. Long soak and eventual
recovery acceptance remain open. No deliberate production outage was injected.

Forecast version 0.0.10 was installed and byte-verified after 455 automated tests.
Phase-6 Core restart 1/2 was requested at 18:43:30 UTC; post-boot acceptance is
recorded in `phase6_review.md`. The sections below are historical checkpoints.

## 2026-09-07 morning: 0.0.8 channel recovery passed; controls blocked

HA 2026.8.3 returned RUNNING at 08:19:33 UTC after restart 2/2. BWALink stopped
was verified before one enable. Installed 0.0.8 automatically recovered twice,
then reached READY on channel 22 in epoch 3 (three allocation attempts total).
Fresh water and target were 37 C; heater OFF. Channel ACK recovery now has actual
hardware evidence. No manual reload was needed to recover these failed attempts.

The 36.5 C HA service test was rejected before transmission by the operating-state
guard. No physical command appears in history; target remains 37 C. Offline
analysis of the successful pre-upgrade capture identified a clean-filter reminder
and a documented ten-byte SETUP variant that 0.0.8 rejects. See
`bp6013_compatibility_review.md` for the local follow-up. Controls were disabled
again via options; the connection stays loaded. Session idle, no spa change.
Phase 6 remains gated by physical-command/session acceptance. Correction boots
used **2/2**; conditional Phase-6 boot allowance **0/2** is not yet applicable.

## Previous checkpoint: captured 0.0.7 failure; 0.0.8 deployment

See `channel_ack_review.md` for current results. 0.0.7 is installed; restart 1/2
completed (RUNNING 2026.8.3 at 07:54:12 UTC). BWALink stopped was verified before
enabling Balboa. First handshake failed; one captured reload also failed. The
correlated channel-22 response arrived in 62.175 ms with another client's CTS/NTS
in the same packet, and no channel-22 CTS followed. This confirms the blocking
condition and shows why deferred CTS cannot recover this controller.

0.0.8 adds bounded backoff/reconnect with a fresh, non-reused nonce, keeping the
existing three-request lifetime limit. Its exact-pattern regression and all 342
core tests pass; actual HA CI also passed (run 34098821512). 0.0.8 is installed
and byte-verified, with the previous directory retained. Restart 2/2 was requested
at 08:15:17 UTC; startup and hardware acceptance are pending. Balboa was disabled
before installation, with controls disabled and no active session. No physical
spa commands have been sent. Acceptance/Phase 6 remain pending; restarts used 2/2.

The sections below are chronological historical checkpoints, **not current
deployment instructions**. Earlier statements such as "not deployed" have been
superseded by newer dated sections above them.

## 2026-09-06 0.0.6 installed and one approved Core restart completed

The user explicitly approved installing 0.0.6 and restarting HA Core. MCP
confirmed BWALink stopped; only the Balboa entry was disabled/unloaded before
replacement. The reviewed archive SHA-256 was verified before extraction, all
41 installed files were compared byte-for-byte, and the previous 0.0.5 directory
was retained under `/config/.balboa-backups/` (resolved `/homeassistant/`).
No config entry, entity identity, `.storage` content, unrelated integration,
Core version or OS version was changed. The one-artifact HA-IP-allowlisted
transfer endpoint closed immediately after delivery.

One MCP Core restart was initiated at 19:20:50 UTC. RUNNING / Core 2026.8.3 was
verified at 19:25:21 UTC. Balboa remained disabled across boot, avoiding startup
channel allocation. BWALink was verified stopped again before one enable.
The HA integration page visibly reports **Version 0.0.6**, one device, three
entities. The bounded Balboa error-log query found only HA's normal custom
integration warning, no Balboa exception in that returned window.

New HA-side diagnostic result:

- Entry loaded, DETECTING_PROTOCOL, channel mode, epoch 1, channel unassigned.
- Assignment requested: true; responses: **1**; correlated: **1**;
  eligible reply opportunities: **0**.
- Explicit failure: `Channel assignment timed out; physical controls remain blocked`.
- RX 1,028 / TX 1 / CRC errors 0 / invalid messages 0 / recoveries 0.
- Status fresh; observed water **37 C**, target **37 C**, heater **OFF**.
- Session idle; controls disabled; climate unavailable until full synchronization.

This rules out a wholly missing assignment response or correlation mismatch in
this attempt. It does **not** yet distinguish a batched/non-terminal response,
a response outside the two-second window, or a rejected assigned address. Those
are the remaining ranked hypotheses; do not assert batching proven solely from
these aggregate counters. No additional allocation/reload loop, setpoint, pump,
light or other physical command was sent. Hardware acceptance remains pending.

Deployment/restart verification is complete. The next engineering target is
assignment ACK eligibility, with the recorded case reproduced in the lab before
any further production update. No WLAN repair is a prerequisite for that work.

## 2026-09-06 Gap 10 improvement; direct core READY, HA still blocked

The follow-up 0.0.6 diagnostic package passed 383 tests (including actual HA and
ZIP installation), lint and strict typing. It is **not deployed**; installation
and a production Core restart await approval. See `weak_network_review.md`.

The user changed only EW11 Serial Gap Time from 50 to 10 and confirmed BWALink
stopped. MCP verified the stopped app before the active diagnostic. The weak
WLAN was left intact. [EW11 settings](ew11_settings.md) records the screenshots,
recommended starting configuration and paired receive-only measurements.

At Gap 10, the 20-second passive probe saw 1,455 valid frames, zero TX/CRC errors,
226 TCP reads (mean 6.44 frames/read), no partial tails, 20 invitations and four
eligible reply opportunities. The initial subsequent HA 0.0.5 attempt sent one
assignment request but never obtained ownership. It retained fresh status and
did not issue any physical commands.

Only the Balboa entry was then unloaded. One bounded instrumented direct-core
attempt used the existing channel arbitration without physical command intent:
READY in 1.7 s, channel 0x12, correlated response after approximately 62 ms,
configuration synchronized, RX 118 / TX 5 / CRC 0, recoveries 0. Hooks only recorded
decisions and did not modify protocol behavior. The owned socket closed cleanly.
Re-enabling HA again sent one request without completing ownership. Total observed
assignment requests in this Gap 10 sequence: three (two HA, one direct core).
Do not reset/reload repeatedly to bypass allocation bounds.

Final live state at this checkpoint: HA entry enabled in channel mode, controls
disabled, only climate/connection/session entities, no active session. No setpoint,
pump, light or other physical command was sent. No production reboot or outage
was requested. Hardware acceptance has **not** passed; Phase 6 remains gated.

The software follow-up is local, not deployed: expose fresh read-only status
without making controls available; publish staleness changes even when other
traffic continues; report the existing two-second assignment deadline explicitly;
include aggregate response/correlation/reply-opportunity diagnostics without raw
frames or nonces. Timeout does not allocate another channel or relax any TX guard.
New loopback tests reproduce missing, uncorrelated and batched assignment replies.
The user's MQTT screenshot is tracked in [entity parity](entity_parity.md), with
implemented capability-discovered controls separated from still-missing mappings.

## 2026-09-06 channel acceptance blocked by receive batching

The user explicitly approved channel mode, enabling controls, a half-degree
setpoint reduction/restoration, and a short heating-session test. MCP again
confirmed BWALink stopped. The official reconfigure flow applied
`protocol_mode=channel-rs485` successfully, preserving device/entity identities.
Physical controls were deliberately left disabled until ownership and safe
configuration synchronization could be established.

After roughly one minute, HA still reported no assigned channel, TX 0 and fresh
status. To avoid competing TCP clients, only this newly created integration was
disabled/unloaded before a single 20-second passive diagnostic connection.

Measured receive behavior (no raw capture checked in):

- 1,426 validated frames, TX 0, CRC errors 0; one startup invalid length and six
  discarded bytes.
- 22 TCP reads; 60–123 frames per read, mean 64.82; 20 reads ended mid-frame.
- 19 exact FE BF00 channel invitations, **none at a receive-batch end**;
  zero safe reply candidates under the existing channel/transport freshness gates.
- 447 each of `11 BF07`, `10 BF06`, `11 BF06`; 66 standard status messages
  (`FF AF13`, 27-byte payload), plus the 19 invitations.
- Latest decoded target 37.0 C, heater OFF; the latest current-water reading was
  unavailable. Do not substitute the earlier 37.0 C water observation for this one.

This rules out absent or differently shaped invitations during the probe and
reproduces the acceptance failure: invitations arrive with later bus traffic, so
replying would use an expired transmission opportunity. The source of buffering
(gateway settings versus another path component) is not yet proven. Do not weaken
freshness checks, force classic mode, adopt another client's channel, or replay a
late invitation to make the test pass.

Elfin's local web UI at the gateway's private LAN address requires authentication; the browser
reported invalid/missing authentication credentials. No credentials were guessed,
no barrier bypassed, and no gateway setting changed. User login is needed to inspect
serial-to-TCP buffering/packetization settings and decide a reversible adjustment.

Final state: integration installed but disabled/unloaded, configured channel mode,
controls still disabled, no active session and no spa commands sent. Every agent
test socket is closed. BWALink may run while awaiting this prerequisite; recheck
that it is stopped before resuming testing. The 11 existing channel ownership/TCP
tests passed locally in 0.74 s. No production code changed. Hardware acceptance
has **not** passed; Phase 6 remains gated. Diagnose-guided measurement narrowed
the cause without speculative production writes.

## 2026-09-06 HA restart and installed read-only acceptance

The user restarted HA themselves. The agent sent no further restart command.
After startup, MCP confirmed Core 2026.8.3 RUNNING and BWALink still stopped.
The installed integration was added through its official config flow and loaded
successfully. The initial request supplied an undeclared `mode` field, which MCP
ignored: the schema's actual field is `protocol_mode`, and its default `auto`
was used. Subsequent diagnostics verified the intended read-only behavior.

- HA created `climate.balboa_spa`, `sensor.balboa_spa_connection`, and
  `sensor.balboa_spa_heating_session`; session state is idle, with no blocked reason.
- RX 6,899, TX 0, CRC errors 0, invalid decoded messages 0, recoveries 0;
  five discarded startup bytes. Fresh status age 0.706 seconds at the snapshot.
- State DETECTING_PROTOCOL, mode UNKNOWN_READ_ONLY, candidate CHANNEL_RS485,
  controls disabled. Climate availability remains false until synchronization.
- The integration page shows version 0.0.5, one device and three entities.
  Its original icon loaded successfully (1254 x 1254 pixels), visually verified.
- The bounded Balboa log query found only HA's standard custom-integration warning,
  no Balboa setup exception in that returned window. This is not a whole-HA log audit.

The official reconfigure preflight for `protocol_mode=channel-rs485` succeeded,
but applying it was rejected by automatic safety review: explicit approval for
this live communication-mode change is required. No alternative mode-change path
was attempted. The entry remains in auto/read-only mode; no channel allocation,
queries, or physical control commands have been sent. Request approval for the
mode, enabling controls, and a bounded setpoint/session test with restoration.
Full hardware acceptance and the Phase 6 gate remain pending.

## 2026-09-06 reviewed package installed; Core restart pending

After the user approved installation, the existing authenticated HA web terminal
installed version 0.0.5 into the previously absent
`/config/custom_components/balboa_rs485`. All 41 archive files were validated;
SHA-256 matched
`f6a3dfe040b1338be992492538a7449ae526c709e48c904e62748f65c6823deb`.
Extraction used an isolated staging directory, verified each file against the
archive, and renamed only the new component into place. No existing component or
configuration was overwritten. Empty staging parent directories may remain.
The one-artifact, HA-IP-restricted LAN transfer endpoint closed after delivery.

The requested Core restart was rejected by the automatic safety review because
"Saat asentaa" explicitly approved installation, not the production interruption.
No restart occurred and no alternative restart path was attempted. Explicit user
approval for one Core restart is required next; it temporarily interrupts HA
automations (typically 1–5 minutes). No OS/device restart or upgrade is planned.
The integration has not yet been loaded/configured or hardware-control tested.

## 2026-09-06 production acceptance preflight

The user authorized real-spa commands with BWALink stopped and autonomous later
phases only after current acceptance tests pass. MCP confirmed `local_bwalink`
stopped immediately before these passive connections. HA reports Core 2026.8.3.
The existing HA web terminal works; `/config/custom_components/balboa_rs485`
does not exist. The reviewed 0.0.5 package is not yet installed in production.

- First brief read: RX 61, TX 0, CRC errors 0, invalid length 1, discarded 4 bytes.
- Follow-up bounded read: RX 249, TX 0, CRC errors 0, invalid length 1,
  discarded 8 bytes, invalid decoded messages 0.
- Fresh status: water 37.0 C, target 37.0 C, heater OFF, pump 1 raw 0.
- Addressed `11 BF06/BF07` still appears alongside `10 BF06`; this does not
  establish ownership or permit classic-mode writes. Startup resynchronization
  occurred; the invalid-length counts are retained rather than called error-free.
- Both sockets closed. No configuration queries, channel negotiation, physical
  commands, installation, or HA restart were performed.

Next gate: install the reviewed package and obtain approval for any required
production Core restart. Then validate channel ownership/configuration before
small absolute-setpoint and heating-session tests with original-state restoration.
This preflight is not full acceptance and does not open the Phase 6 gate.

No connection to a real Elfin or spa is part of Phase 0/1. Synthetic fixtures and
external reference vectors do not establish hardware compatibility.

## 2026-09-05 user-authorized Phase 2 passive check

BWAlink was stopped by the user before connecting to the EW11's private LAN address, port 8899.
Both test sockets were closed afterwards; the user was told BWAlink could restart.
No configuration request or physical command was sent.

- Passive observer: displayed 30 frames from a 60-frame parsed batch; TX 0,
  CRC errors 0, invalid length 1, discarded startup bytes 11. Joining midstream
  is one possible explanation for startup resynchronization, not proven here.
- Decoded water 37.0 C, target 37.0 C, heater OFF, pump 1 raw 0. Panel comparison
  has not been performed.
- Received `10 BF 06` alongside `11 BF 06` and `11 BF 07`. These are channel
  indicators, not evidence of exclusive ownership of the classic address.
- Separate 15-second runtime auto check: RX 1,056, TX 0, CRC errors 0, invalid
  messages 0, recoveries 0, final rolling traffic rate 68.4 frames/s.
- Runtime stayed DETECTING_PROTOCOL / UNKNOWN_READ_ONLY with channel candidate;
  availability was false, as required without supported protocol/configuration.

This is **not** a 24-hour soak or validation of channel negotiation. No raw capture
was checked in. Hardware writes remain disabled pending protocol ownership work,
configuration validation and the staged checks below.

After simulator and HA/simulator testing pass, explicitly approve each stage:

1. Read-only Elfin connection and 24-hour soak: capture framing, CRC rate, status
   values versus panel, READY addresses/intervals, bridge batching/latency, model,
   firmware and configuration. Confirm 115200/8N1 against the actual installation.
2. Supported absolute set-temperature command only, with observed confirmation.
3. One pump or light at a time; verify capabilities and every physical transition.
4. Elfin disconnect/reboot and HA restart; test stale sockets and recovery.
5. Normal automations including session expiry/restart and actual energy inputs.
6. 72-hour soak with diagnostics and independently observed command outcomes.

Never transmit unknown or experimental frames. Never replay stale toggles.
Document firmware and topology with every capture and redact identifying data.
Do not infer bus safety from a successful TCP write or an anecdotal implementation.
Before enabling TX, resolve classic/addressed CTS applicability, latency budget,
fresh-status verification, and direct-RS485 configuration/identity requirements.
