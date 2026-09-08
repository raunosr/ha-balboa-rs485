# Phase 4 — device transport, Home Assistant and HACS packaging

User approval: proceed with the channel prerequisite and HA basics, with HACS
compatibility and an original icon. Stop before heating sessions (Phase 5).
Preserve the private GitHub repository; HACS itself requires a public repository,
so actual HACS installation/publication is a separate user decision. A complete
manual-install ZIP can be delivered while the repository remains private.

Approved interfaces and behavior-first slices:

1. Research channel ownership; never adopt a quiet channel or replay a fixed
   channel after reconnect. Test correlated assignment, wrong nonce/address,
   fresh addressed CTS, collision/reconnect and ambiguous command outcomes with
   real loopback streams before any separately coordinated hardware test.
2. Package the independent core with the integration without private pip/GitHub
   dependencies or Home Assistant imports in that core. Verify the install
   artifact in isolation, not only the repository's editable import path.
3. Config flow and connection ownership: one socket, bounded configuration check,
   protocol/status gating, duplicate prevention and stable entry identity;
   unload/reload/shutdown await cleanup, including failed setup paths.
4. Push observations into capability-aware climate, pump, light and accessory
   entities. Service calls submit desired values and await verification; they
   never update physical state optimistically. No fake HVAC OFF semantics.
5. Connection/options/diagnostics, redaction, dynamic capability changes, stale
   availability and simulator-backed Home Assistant tests. Separate pure core
   tests from Linux/Home Assistant dependencies; no mock HA framework as proof.
6. HACS manifest, reproducible install ZIP, English/Finnish strings, bundled local
   brand image, documentation, validation, review and stop.

The user confirmed Home Assistant **2026.9**; target minimum **2026.9.0** and
test against that exact core release with Python 3.14 in Linux CI.
Home Assistant 2026.3+ supports `brand/` inside a custom integration. Windows has
no WSL installation here; use Linux CI for actual HA integration tests rather
than modifying the user's operating system. Exact supported/tested versions
and remaining hardware limitations will be recorded in the phase review.

## Identity and connection ownership

There is no verified globally unique hardware identifier in the supported direct
RS485 messages. Do not invent one from the model, configuration signature or IP.
Manual ConfigEntries use HA's persisted `entry_id` for entity/device identifiers.
Reconfigure the same entry when moving its endpoint; this preserves registry and
history identity. Removing and recreating an entry creates a new identity.
Duplicate prevention compares normalized host/port; aliases of one device cannot
be deduplicated reliably without a verified hardware identifier. One entry per
physical controller remains an installation requirement.

The config flow only listens for a validated standard status, even if the user
selects an explicit protocol. Setup owns the sole long-lived runtime and performs
supported configuration queries. Valid status permits retaining an entry whose
protocol remains read-only; it does not make control entities available. This
avoids repeated HA setup retries consuming channel assignments for an otherwise
live bus. Physical controls are disabled by default and require a separate option.
