# Native observations and controls — Phase 4B

The current complete implementation guide is
[Native controls 0.0.14](native_controls_0_0_13.md). Production acceptance is recorded
in `phase4b_review.md`. Existing climate, fan, light, accessory and prediction IDs
are preserved. The text below documents the historical 0.0.12 first increment;
its pending-work statements do not describe the current 0.0.14 source.

## Observations without a control channel

These sensors use fresh decoded status, even in passive read-only mode. A socket
or other traffic cannot keep stale values available. Missing/unsupported values
are unknown; disconnected or stale status is unavailable. They open no extra
connection and send no query or physical command.

| Sensor | Meaning |
| --- | --- |
| Water temperature | Measured water temperature with native HA temperature statistics; not the target |
| Heater state / Heater running | Off, heating or waiting; waiting is **not** heater-on; unknown state is not silently off |
| Heating mode | Ready, Rest or the observed Ready-in-Rest transient |
| Temperature range | Currently active Low / High profile |
| Reminder | Recognized reminder text; unrecognized reminders retain their numeric code. Not a pH/sanitizer measurement or fault-clear action |
| Spa clock / Clock format | Observed local HH:MM and 12/24-hour display; invalid clock bytes remain unknown |
| Hold / Priming | Separate status observations; initialization is not Hold. No automatic maintenance/priming exit |
| Panel locked / Settings locked | ON means locked. The settings bit can also indicate a controller test condition; it remains a conservative write inhibitor |

The controller's dedicated circulation-pump bit is not the same thing as Pump 1
low speed. Its capability/model interpretation and filter-running bit evidence
remain gated; this increment does not create misleading substitutes.

## Device information and diagnostics

Model and software version come from the controller's information response, and
update after discovery. The old MQTT 2.3.2 label came from the BWA Link software,
not the controller. The installed integration version is a third, separate value.

Four diagnostic sensors expose the assigned channel, CRC errors, recoveries and
remaining channel-allocation attempts. Counts cover the current runtime, not
permanent historical totals. Classic RS485 has no negotiated channel: the channel
sensor is unknown, not its fixed command address. Passive mode similarly has no
assigned channel. The three-allocation limit is unchanged and must not be bypassed
by repeated reloads. Remaining attempts are not a promise of successful recovery.

Per-frame counts and detailed timing remain in downloaded, redacted diagnostics
to avoid high-frequency recorder traffic. These four diagnostics stay readable
while physical control is unavailable.

## Named Pump 1 control

The additional select offers Off / Circulation (1) / Jets (2) on the user's
two-speed Pump 1, and Off / On on a supported single-speed variant. It uses the
same observed-state engine as the existing fan entity; either interface updates
the other from status, never optimistically. Circulation is a speed label, not
proof of water flow. Filtration/heating may prevent the controller stopping a
pump; an unconfirmed request is not reported as success.

Only supported choices are exposed. The old fan ID remains usable, including by
existing automations. Physical-control permission, freshness and safety guards
still apply.

## Low/High presets and session ownership

The existing climate entity offers Low (maintenance) / High (bathing). Selecting
one changes only the active range, using that profile's own stored target. It
does not rewrite its temperature or change Ready/Rest. The inactive target is
not guessed from the active one and is not silently read by switching profiles.

Range changes are rejected while a legacy heating session is active or restoring.
Finish/cancel the session and wait for restoration before switching ranges. A
manual target change retains the existing explicit behavior: abandon the legacy
session durably before writing the new target. Manual settings and session starts
are serialized through storage and command completion, so concurrent calls cannot
save one range and write a target to the other.

The [HA climate preset contract](https://developers.home-assistant.io/docs/core/entity/climate/#presets)
is used instead of heat/cool dual targets, which would mean something different.

## Ready / Rest heating policy

The Heating policy select offers Ready / Rest separately from the climate's
temperature range. Ready-in-Rest is a temporary observed state, shown by the
Heating mode sensor, not an option to request; the policy select is unknown during
that transient. A request for Ready from that state uses the existing individually
observed/verified transition through Rest. Mode changes are also blocked during
legacy sessions. Rest is not power-off and may heat during filtration.

## Still separate work

The durable 36.5 C minimum bathing session with High-target/range/mode restoration,
four native filter start/end controls, filter-running evidence, clock/unit writes,
and supported advanced maintenance actions remain subsequent Phase-4B increments.
The existing heating-session action still restores an explicitly supplied
maintenance target **within its current range**; it must not be described as the
new range-aware session.

See the complete [MQTT inventory and agreed design](phase4b_design.md),
[EW11 recommended settings](ew11_settings.md), and
[HA installation guide](home_assistant.md).
