# BWALink transport comparison — 2026-09-08

Status: source comparison completed; no new transport deployed. Automatic recovery
remains an open requirement, not a passed hardware gate. Existing 0.0.15 is unchanged.

## Evidence and version boundary

The installed BWALink app reports version 2024.8.0, `socat=false`, stopped, manual
boot and watchdog enabled. The user restored High with BWALink and then stopped
it. Independent integration telemetry subsequently showed target/water 37.5 C;
controls are disabled and session intent is null. The passive temperature alone
does not independently prove the range bit. No new spa command or restart was
performed during this comparison.

Source facts were rechecked against the existing pinned checkouts:

- [BWALink entrypoint](https://github.com/jshank/bwalink/blob/bab3dea3a667908a691326976c60522824c00efb/ha-addon/docker-entrypoint.sh)
  selects a direct `tcp://` URI when socat is disabled; the optional serial proxy
  invokes socat with reconnect options. [Its Dockerfile](https://github.com/jshank/bwalink/blob/bab3dea3a667908a691326976c60522824c00efb/ha-addon/Dockerfile)
  installs an unpinned Ruby gem. The app version does **not** establish the exact
  installed gem source; this comparison is not an audit of its container image.
- [Ruby client](https://github.com/ccutrer/balboa_worldwide_app/blob/a9031c7c4b3060ecb093f1c74ee42b45ef89934c/lib/bwa/client.rb):
  fixed source 0x0A; direct socket writes on TCP. Serial/RFC2217/ESPHome instead
  queue a message until a Ready message, without an addressed-channel check.
  No negotiated-channel handshake is implemented. Range selection compares the
  latest status then sends one toggle; it does not verify that transaction.
  Pump changes precompute toggle counts. EOF/reset handling retries reads; no
  replacement TCP socket is created by this client after initial construction.
- [Ruby MQTT bridge](https://github.com/ccutrer/balboa_worldwide_app/blob/a9031c7c4b3060ecb093f1c74ee42b45ef89934c/exe/bwa_mqtt_bridge)
  creates one client, publishes status-derived state, and emits systemd watchdog
  notifications. That alone does not establish working end-to-end reconnection in
  the installed HA app. Supervisor watchdog being enabled is a separate fact.

Only behavior was studied; no upstream code or assets were copied.

## Important safety finding: retry pacing is not allocation safety

The [protocol wiki's channel description](https://github.com/ccutrer/balboa_worldwide_app/wiki#channels)
reports incrementing assignments, no CTS on 0x30–0x3F, and power cycling as the
only known allocation reset. This is a community reverse-engineering report,
not a confirmed property of every controller. It rules out assuming that an
elapsed timer frees a channel. A three-per-five-minute limit still permits
unbounded lifetime allocations.

Therefore the local rolling-window recovery experiment was **rejected before
deployment** and removed from canonical code; the bundle was never changed. Its loopback
test only proved software reconnect after three losses; the simulated peer did
not model finite controller allocations. The draft and its tests are retained
privately under ignored `.research/` for audit, not as a release candidate.
Do not revive it solely because those tests passed.

## What this explains, and what it does not

BWALink's successful High command follows a different transmit policy. It is not
evidence that the integration's assignment ACK succeeded. Our historical capture
already proves a correlated offer followed by another client's traffic with no
eligible ACK slot. See `channel_ack_review.md`.

The current diagnostics show one correlated offer, zero eligible reply
opportunities and three consumed requests. They do not expose the offered
address or the rejected packet tail. Thus current channel-pool exhaustion is a
**hypothesis**, not a diagnosis. The available old capture (channel 22) and
successful channel 32 do not settle the most recent failure. Do not allocate
another channel merely to find out. No spa power cycle is requested here.

## Next bounded engineering step

Study an explicitly selected fixed-address direct RS485/TCP transport in the laboratory,
separate from negotiated channel mode. Keep observed-state confirmation,
single-writer ownership, bounded memory, dead-socket closure, cancellation and
no replay of ambiguous toggles. Never turn a TCP URL into automatic permission
to bypass raw-RS485 arbitration, or silently reinterpret existing BWA_TCP mode.

Before a production compatibility trial, make its different bus scheduling and
collision risk explicit. Capture TX/RX evidence with only one writer active;
confirm observed results independently. Do not restart HA, start BWALink, relax
guards, or change transport settings merely as part of source research.
Reusing a previous channel also needs positive ownership/revalidation evidence,
not the absence of other traffic. Long-duration recovery must include a finite
channel-pool simulator before it can be called safe.

The bounded filter gate passed on 0.0.15, but the Low-to-High bathing test and
weak-link recovery gate did not. Phase 7 and automation migration remain deferred.

## Verification after shelving the draft

43 channel/session/connection tests passed in 12.32 seconds. Ruff lint/format,
strict core typing, bundled-core equality and `git diff --check` passed. Final
tracked changes are documentation only; no new release, CI run or HA installation
was performed. These checks do not establish production recovery acceptance.

The subsequent user-authorized laboratory implementation is recorded separately
in `direct_tcp_lab_review.md`. Technical connection names are used; the rejected
rolling-allocation experiment remains rejected.
