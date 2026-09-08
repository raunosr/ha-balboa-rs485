# EW11 settings and weak-WLAN validation

These settings describe the user's Elfin EW11, web firmware
`build23092615012212889`, as observed on 2026-09-06. They are not a guarantee for
every Balboa controller. BWALink must be stopped before this integration connects.
Do not run a diagnostic client and the HA integration against the bus together.

## Recommended starting configuration

| Setting | Value | Evidence / qualification |
| --- | --- | --- |
| Serial baud / data / parity / stop | 115200 / 8 / None / 1 | Existing working BWALink setup; valid Balboa frames received |
| Serial flow control | Half Duplex | Existing RS485 configuration |
| Serial protocol | None | Raw transparent protocol, no Modbus conversion |
| Serial Buffer Size | 512 | Retained; not independently optimized |
| Serial Gap Time | **10 ms** | User changed only 50 to 10; greatly reduced batching and enabled one complete direct-core handshake |
| Socket protocol | TCP Server | The integration is the TCP client |
| Local Port | 8899 | Match the integration; not a protocol-mandated port |
| Socket route | Uart | Raw serial bridge |
| Socket Buffer Size | 512 | Retained; not independently optimized |
| Keep Alive | 60 s | Retained; integration additionally monitors valid/status/CTS traffic |
| Socket Timeout | 0 s | Retained; does not disable integration health deadlines |
| Max Accept | 3 | Existing capacity, **not** permission to run competing control clients |

Other settings were left unchanged: CLI Serial String `+++`, Waiting Time 300,
and socket Security shown as Disable. This records the existing configuration,
not a recommendation to disable authentication or weaken network security. Keep
the EW11 on a trusted LAN; never expose its serial port or management UI publicly.
Do not bypass the web UI's limits or change unrelated settings to chase timing.

## Measured change (20-second receive-only probes)

The user reported roughly -80 dBm RSSI and an offline WLAN access point. No WLAN
repair, HA restart, EW11 restart, or deliberate production outage was required
for these measurements. Only Gap Time changed between the paired observations.

| Measurement | Gap 50 ms | Gap 10 ms |
| --- | ---: | ---: |
| Validated frames | 1,426 | 1,455 |
| TCP reads | 22 | 226 |
| Mean frames per read | 64.82 | 6.44 |
| Reads with partial trailing frame | 20 | 0 |
| Channel invitations | 19 | 20 |
| Invitations eligible for a fresh reply | 0 | 4 |
| CRC errors | 0 | 0 |
| Transmitted frames | 0 | 0 |

After the change, one bounded direct-core attempt reached READY in 1.7 seconds:
correlated assignment, own channel `0x12`, configuration replies and fresh status.
The assignment response arrived approximately 62 ms after the request. Five total
frames were transmitted (management/configuration/idle traffic), no physical
control commands. The probe closed its owned socket after the result.

The installed HA 0.0.5 runtime still failed to finish assignment in two observed
attempts (one request each). **Gap 10 is a better tested starting point, not a
complete fix or proof of production control reliability.** The original failure
cannot be attributed solely to WLAN or serial batching. Compare HA-side request,
response/correlation and eligible-reply diagnostics before further live attempts.

The subsequent approved HA 0.0.6 deployment confirmed one correlated assignment
response but zero eligible ACK opportunities. Missing response and wrong nonce
are ruled out for that attempt; batching, lateness and address rejection still
need separating. See `hardware_validation.md`. This does not change the Gap 10
starting recommendation or establish full hardware acceptance.

On 2026-09-07 a HA-side capture confirmed a correlated assignment response grouped
with another client's CTS/NTS, closing the immediate ACK slot. Installed 0.0.8 then
demonstrated bounded recovery: two failed attempts, then READY/channel 22 in epoch
3 without manual intervention. This was still the existing weak WLAN/Gap 10 setup.
Subsequent target testing was blocked by distinct clean-filter-reminder and
ten-byte SETUP compatibility issues, not by an unassigned channel. See
`channel_ack_review.md` and `bp6013_compatibility_review.md`. CRC errors were observed
during the connection and remain part of later command/soak acceptance; they are
not hidden or attributed conclusively to WLAN alone.

Never answer a buffered old invitation, adopt another client's address, or replay
toggles to compensate for delay. Keep fresh read-only observations separate from
control readiness and mark observations unavailable when stale. Failure injection
belongs in the simulator, not the production HA network.
