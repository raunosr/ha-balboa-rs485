# Native entity coverage versus the user's MQTT device

Reference: the user's 2026-09-06/07 screenshots of BP6013G2 in BWALink MQTT.
The displayed 2.3.2 is the bridge version (`BWA::VERSION` in its discovery code),
not controller firmware evidence. The 2026-09-07 live MQTT registry inventory
contains 26 entities. See [Phase 4B design](phase4b_design.md) for the complete
inventory, native UX proposal, dual-range sessions and additional feature research.
This is a feature checklist, not proof that every advertised MQTT control
worked on the physical controller. The native integration currently creates the
climate, connection and heating-session entities before capability discovery.
Supported accessory entities are added once configuration is synchronized; an
empty initial device page is **not** the intended finished UI.

The adapter foundation was completed in Phase 4, but not every native mapping.
The Phase 4B implementation is now installed as 0.0.14; its production acceptance
is incomplete. See the current checkpoint in `phase4b_review.md` before treating
this inventory as an operational handover. Phase 4B follows Phase 6 and precedes
energy work (Phase 7).
Prediction adds five native sensors and model diagnostics in Phase 6. Frontend
Phases 8/9 present native entities; they do not implement missing backend controls.

| MQTT feature in screenshot | Native adapter status / remaining work |
| --- | --- |
| Hot Tub, target water temperature | Climate implemented; observed current/target/action and verified target writes. Separate target slider unnecessary when climate provides it |
| Pumps 1/2/3 | Capability-discovered fan entities implemented; actual number/speeds must come from controller |
| Lights | Capability-discovered light entities implemented |
| Heating mode / temperature range | 0.0.12 increment: observed mode/range sensors and native choices; production acceptance pending |
| Current water temperature | 0.0.12: independent fresh passive temperature sensor with statistics, plus existing climate attribute; production acceptance pending |
| Circulation pump running | 0.0.13 native capability-gated binary sensor; distinct from Pump 1 low speed |
| Filter cycle 1/2 schedule / cycle 2 enabled | 0.0.13 four HH:MM start/end controls, durations and Cycle 2 switch; fresh read/modify/write/readback, no replay |
| Filter cycle 1/2 running | 0.0.14 BP6013G2: Cycle 2 bit established at natural end, Cycle 1 source-inferred; other models retain consensus/unknown behavior |
| 24-hour time / temperature scale | 0.0.13 native display-format switch, clock time and unit select; observed verification |
| Hold / priming | Separate observations and guarded Hold control; no priming exit |
| Clear Notification | 0.0.13 acknowledge recognized reminder only; never clear fault history or unknown alarms |
| Normal Operation / Soak | 0.0.13 guarded buttons: exit Hold / request supported pumps off, respectively |
| Heating sessions | Durable legacy sessions plus 0.0.13 36.5 C-minimum High bathing session and per-field restoration; native buttons/preferences |

The 0.0.13 implementation additionally exposes historical fault/count and refreshed
metadata diagnostics. It includes the 0.0.12 heater state/running, reminders, locks,
controller model/software, selected diagnostic counts and named Pump 1 speeds.
See [current native guide](native_controls_0_0_13.md) and [review](phase4b_review.md).

Remaining native-entity gaps must be explicitly reviewed before claiming the
finished integration replaces this MQTT device. They are not automatically
completed by connecting successfully, and frontend cards cannot substitute for
missing native entities. Add supported mappings with simulator tests and bounded
hardware confirmation; omit unsupported hardware capabilities rather than invent
controls. Phase 6's short acceptance gate has passed; full parity and long-duration
recovery remain explicit final-acceptance work.
