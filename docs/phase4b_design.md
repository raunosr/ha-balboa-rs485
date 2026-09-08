# Phase 4B — native coverage and range-aware sessions

Status: first implementation increment in progress, 2026-09-07; **not installed**.
See `phase4b_review.md` and `native_entities.md` for implemented versus pending
items. This document remains the full contract, not a claim of completed parity.
Phase 6 is complete in 0.0.11; this work precedes Phase 7. The existing Phase-5 session
changes one target in the current range; it does NOT yet implement the dual-range
restoration described here. No new spa command or HA restart was used for this
inventory. BWALink stayed stopped; no competing connection was opened.

## Evidence and terminology

The HA MQTT device registry returned 26 entities for BWA Link / BP6013G2, all
unavailable because BWALink is stopped. Names/options/ranges below are registry
facts, not successful hardware-control tests. The user's two screenshots agree.
The existing native device has 12 entities after prediction installation.

The pinned Ruby MQTT bridge and its message/client code were inspected alongside
pybalboa and HA's native Balboa adapter (revisions in `protocol_sources.md`).
BWALink's Dockerfile installs the Ruby gem without a pinned version, so a current
upstream snapshot is not proof of the exact installed executable. One important
metadata correction: Ruby publishes `BWA::VERSION` as MQTT `sw_version`; the old
device's 2.3.2 label is the bridge version, not evidence of controller firmware.
Our own BF24 observation reports software ID M100_226, version 43.0, setup 12.

User-specific Pump 1 labels: 0 off, 1 circulation/low speed, 2 jets/high speed.
Pump 2/3 are single-speed. Do not conflate Pump 1 low with the separate controller
circulation-pump status bit, or infer a flow measurement from either one.

## Complete MQTT inventory and proposed native presentation

All old IDs below have the prefix shown; none will be renamed or deleted by this
work. New integrations should preserve their existing IDs too.

| Existing MQTT entity ID | Native presentation / decision |
| --- | --- |
| `water_heater.bwa_link_hot_tub` | Existing climate: actual water, active target and observed heating action. No fake physical OFF mode |
| `number.bwa_link_hot_tub_target_water_temperature` | Climate target plus a combined range/target action; avoid duplicating the active target slider |
| `select.bwa_link_hot_tub_temperature_range` | Climate presets Low / High, clearly described as Ylläpito / Kylpy; advanced select can alias the same verified intent |
| `select.bwa_link_hot_tub_heating_mode` | Ready / Rest selection; Ready-in-Rest is an observed transient state, not a directly selectable target |
| `select.bwa_link_hot_tub_temperature_scale` | Celsius / Fahrenheit configuration, only after tested write/confirmation semantics |
| `switch.bwa_link_hot_tub_24_hour_time` | Clock-format configuration; must not silently reset the spa clock |
| `number.bwa_link_hot_tub_pump_1` | Named select Off / Circulation (1) / Jets (2); retain the existing fan entity for compatibility |
| `switch.bwa_link_hot_tub_pump_2` | On/off presentation; preserve existing native fan ID rather than silently migrating domains |
| `switch.bwa_link_hot_tub_pump_3` | Same single-speed treatment as Pump 2 |
| `light.bwa_link_hot_tub_lights` | Existing capability-discovered light |
| `switch.bwa_link_hot_tub_hold` | Hold status first; bounded maintenance Hold control only after command-specific guard/exit tests |
| `button.bwa_link_normal_operation` | Advanced one-shot normal-operation action; not a heating-session start button |
| `button.bwa_link_soak` | Advanced quiet/all-pumps-off request, NOT our timed heating session; acceptance requires observable outcome and safety review |
| `button.bwa_link_clear_notification` | Acknowledge a supported reminder only; never silently clear fault history or bypass safety faults |
| `number.bwa_link_filter_cycle_1_start_hour` | Merge hour/minute into native Cycle 1 start time |
| `number.bwa_link_filter_cycle_1_start_minute` | Same Cycle 1 start time, no separate minute slider |
| `number.bwa_link_filter_cycle_1_duration` | Prefer Cycle 1 end time with read-only calculated duration |
| `number.bwa_link_filter_cycle_2_start_hour` | Merge hour/minute into native Cycle 2 start time |
| `number.bwa_link_filter_cycle_2_start_minute` | Same Cycle 2 start time |
| `number.bwa_link_filter_cycle_2_duration` | Prefer Cycle 2 end time with read-only calculated duration |
| `switch.bwa_link_filter_cycle_2_enabled` | Separate Cycle 2 enable switch; preserve its stored times while disabled |
| `binary_sensor.bwa_link_filter_cycle_1_running` | Actual Cycle 1 running sensor after resolving bit-layout evidence; not calculated solely from the clock |
| `binary_sensor.bwa_link_filter_cycle_2_running` | Same for Cycle 2 |
| `binary_sensor.bwa_link_hot_tub_circulation_pump_running` | Controller circulation status, distinct from Pump 1 low; capability/model verification required |
| `sensor.bwa_link_hot_tub_current_water_temperature` | Native temperature sensor with history/statistics, alongside climate attribute |
| `binary_sensor.bwa_link_hot_tub_priming` | Read-only priming status; never end priming automatically to make controls available |

The old unavailable water-heater entity advertises 43.3..60 C while its separate
target number advertises 10..40 C. Neither is authoritative validation: use fresh
controller SETUP limits, units and step. Preserve unknown values as unknown.

## Main temperature UX

Recommended first interface: one climate entity, presets **Low (maintenance)** /
**High (bathing)** and the active target. These are mutually exclusive stored spa
profiles, not HA's simultaneous heat/cool lower/upper target band. Selecting a
preset alone does not overwrite its temperature or change Ready/Rest.

For automations offer one composite range-and-temperature action. The independent
command/session layer sequences and verifies its steps; callers must not create
delays between separate range and target writes. No competing client or socket.

Balboa documents independent targets per range. The reviewed status message only
reports the active target, and SETUP reports limits, not both saved targets.
Therefore show the inactive target only as **last observed**, with timestamp and
unknown before first observation. Do not query it by silently switching ranges
during normal refresh. Persisting a cached value does not make it fresh.

Two simultaneously editable temperature boxes would need either explicit HA-owned
desired settings (clearly not device readback), or a durable switch/edit/restore
operation that briefly activates the other profile. Do not hide that physical
side effect. Prefer the climate plus composite action initially; expose separate
boxes only with an explicit apply policy. No extra user-created helpers are needed
for the basic integration.

## Range-aware heating session contract

Suggested native start/end buttons wrap the existing durable session engine.
Default minimum bathing target is the user's **36.5 C**, configurable as a session
preference, not a universal hardware constant. At start:

1. Require fresh safe state. Persist original range, unit, observed active target,
   original heat mode, deadline, operation identity and restoration ownership
   before changing anything. Do not accept an overlapping session.
2. Request High and observe its confirmation. Capture High's freshly reported
   original target and persist it **before** overwriting it. If a crash occurs
   before capture, do not invent the missing target or perform a heating write.
3. Session target is `max(original_high_target, minimum_bathing_target)`, validated
   against the controller's High bounds/step. Thus 35 -> 36.5, 36.5 unchanged,
   38 unchanged. This is not a command to force all sessions to exactly 36.5.
4. Ready/Rest is a separate axis: High in Rest may not heat outside filtration.
   For a heat-now session, temporarily request Ready if needed and retain the
   previous stable mode for restoration. Ready-in-Rest cannot be set directly;
   record it as transient and use its underlying Rest policy, never replay jets
   to recreate it. This policy must be clear in the start action's description.
5. On expiry/cancel, restore the original High target while High is active, then
   restore the original range and any session-owned heat-mode change. If already
   High at start, remain High afterwards. Do not overwrite Low's stored target.

The transaction must survive a crash after every step, including between a
successful physical change and its confirmation/save. Recovery always checks the
deadline first, reconciles fresh observations, and never replays saved toggles.
Expired sessions resume restoration, not reheating. Persistent restoration stays
pending while HA/network/control ownership is unavailable. It cannot execute on
the spa while HA is offline; the UI must show that limitation honestly.

Existing manual HA target changes abandon the old single-target session. For the
new multi-field session, define ownership per field: explicit manual changes must
not be overwritten later by a stale saved value. Unchanged session-owned fields
still need cleanup. Surface ambiguous panel/external edits rather than guessing.
Keep legacy session records readable and preserve their original semantics.

## Filter-cycle UX and transaction boundaries

Use four native time entities: Cycle 1 start/end and Cycle 2 start/end, plus Cycle
2 enabled. Example: 22:00 -> 02:00 displays a four-hour duration. Times mean the
spa's own local wall clock, not UTC or a weekly HA Schedule helper. Display spa
clock and clock mismatch separately; do not silently change it when changing the
12/24-hour display format.

The wire update includes both schedules, so changing one field must use fresh
read-modify-write, preserve the other cycle and confirm the resulting full record.
Serialize concurrent changes; never mark success merely because bytes were sent.
Provide one compound action for changing start/end together to avoid an unwanted
intermediate schedule. Start changes should retain duration by default; changing
end changes duration. Document these choices.

Zero and 24-hour durations need explicit semantics: Ruby's MQTT range is 0..1439,
pybalboa supports 15..1440 and equal start/end means 24 hours there. Do not silently
infer zero versus continuous filtration from equal clocks. Hardware support and
boundary tests gate any continuous option; retain unsupported observed values
read-only rather than rewriting them.

## Useful additions beyond the 26 MQTT entities

| Addition | Evidence / intended exposure |
| --- | --- |
| Heater state: off / heating / waiting | Already distinct in core; native enum plus actual-heating binary sensor. Waiting is not heater-on |
| Reminder description | Ruby already publishes a notification topic without a dedicated HA entity. Expose recognized reminders and retain unknown codes |
| Latest fault and new-fault event | Existing fault query/parser plus HA reference event mapping. Historical fault is not automatically an active alarm; no log erasure |
| Spa clock and optional explicit synchronization | Observed hour/minute already decoded; a clock-set action must be deliberate and verified |
| Panel/settings locked, Hold and priming | Read-only safety diagnostics first; no automatic unlock or priming exit |
| Session phase, end time, remaining duration, restoration blocked reason | Extend the existing durable session entity for the new multi-step operation |
| Channel, data age, reconnects, CRC errors, allocation budget and command outcomes | Already mostly present in downloaded diagnostics; add selected diagnostic entities, low update rate and disabled-by-default noisy counters |
| Controller model, software ID/version, setup and capabilities | Correct Device info and diagnostics; distinguish bridge/package version from controller firmware |
| Additional pumps/lights, blower, mister and auxiliary outputs | Only when controller capabilities and agreed semantics support them; never create phantom controls |
| Cleanup-cycle duration, reminder preferences and M8 | Research candidates, not promises for BP6013G2. Preferences support/model evidence and bounded verification required |

A/B temperatures in a historical fault must not become current water sensors.
No pH, sanitizer concentration, flow, measured watts/kWh or EW11 RSSI is available
from the reviewed normal status stream. Reminder text is not a chemical reading.
Energy needs the separate Phase-7 measured input; RSSI needs gateway-specific data.
Do not expose controller setup/DIP changes, GFCI tests, factory resets, test modes,
Wi-Fi configuration or other hazardous/unknown writes as ordinary controls.

## Open evidence and implementation order

- Filter-running layout is disputed: Ruby and pybalboa use status byte 9 masks
  0x04/0x08, while the community wiki lists bits 3/4. Agreement in two libraries
  is not proof for this controller. Use existing captures or a passive transition
  correlated with the panel; do not change filtration merely to force evidence.
- Soak, Normal Operation, Hold exit and reminder clear require command-specific
  safety/confirmation rules; don't weaken normal-state guards globally.
- Device clock, Celsius/Fahrenheit and inactive-target edits affect other state.
  Include them in transaction/restart/ownership tests rather than isolated toggles.
- The existing three-allocation lifetime limit remains an open long-duration
  acceptance issue, independent of prediction/entity count. No repeated reloads
  to bypass it and no claim that full weak-network resilience is complete.

Implementation slices: (1) observed sensors/device info/diagnostics; (2) named pump
and range/mode controls; (3) durable range-aware session with legacy migration;
(4) filters and clock/preferences; (5) supported advanced actions and hardware
acceptance. Each slice needs source evidence, simulator tests, actual HA tests,
lint/types and review. The user subsequently granted three production restarts
for autonomous completion/deployment; track usage in `phase4b_review.md`.

## Source links

- [Balboa TP600/TP400 guide, pages 4-6](https://www.balboawater.com/wp-content/uploads/2024/12/TP600-and-TP400-USER-GUIDE_Standard-Menus_40940.pdf): independent ranges, pumps and heat modes; manufacturer/model limits apply.
- [Pinned Ruby MQTT bridge](https://github.com/ccutrer/balboa_worldwide_app/blob/a9031c7c4b3060ecb093f1c74ee42b45ef89934c/exe/bwa_mqtt_bridge): discovery, version attribution, notification/heating topics and controls.
- [Pinned Ruby status parser](https://github.com/ccutrer/balboa_worldwide_app/blob/a9031c7c4b3060ecb093f1c74ee42b45ef89934c/lib/bwa/messages/status.rb): observations, including filter bit interpretation.
- [Pinned pybalboa client](https://github.com/garbled1/pybalboa/blob/845c0c65f367d434be042f9683a1a4f19ffdd0ac/pybalboa/client.py): active target, filter time conversion and duration limits.
- [Protocol wiki](https://github.com/ccutrer/balboa_worldwide_app/wiki): additional preferences and explicitly unresolved differences; not a vendor guarantee.
- [HA Time](https://www.home-assistant.io/integrations/time/), [Select](https://www.home-assistant.io/integrations/select/) and [Climate presets](https://developers.home-assistant.io/docs/core/entity/climate/#presets): native presentation options.
- [HA Fan contract](https://developers.home-assistant.io/docs/core/entity/fan/#preset-modes): manual speeds must not be represented as fan presets; use a separate named select for Pump 1 UX.

No upstream implementation code was copied. HA best-practice guidance favored
native entities and stable IDs rather than an extra layer of templated helpers.
