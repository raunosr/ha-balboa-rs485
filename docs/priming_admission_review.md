# Priming: per-control admission, not a global command lock

Status: local correction; not released or hardware accepted.

## Finding and evidence

The `priming` rejection was generated before transmission by this integration's
global normal-state gate. The inspected pinned Ruby client decodes the same
status byte as priming but does not use it to reject pump/light setters. Its
behavior explains why working controls in another client do not by themselves
prove that reconnect fixed the underlying state. The exact installed Ruby gem
revision was not verified. The origin of the unexpected priming telemetry remains
unresolved; a separate read-only gateway observation also contained that field.

Balboa's [TP600/TP400 user guide](https://www.balboawater.com/wp-content/uploads/2024/12/TP600-and-TP400-USER-GUIDE_Standard-Menus_40940.pdf),
reviewed 2026-09-13, describes priming as a mode for manually running pumps with
the heater disabled. It also says the Light button can run a dedicated circulation
pump in that mode. This is panel documentation, not a guarantee of every RS485
command's interpretation. The implementation therefore keeps a narrow allowlist,
not the upstream client's unrestricted write behavior. No upstream code copied.

## Change

- Keep the priming sensor and raw status interpretation unchanged.
- `controls_safe` remains general/heating/session readiness, false in priming.
  `safe_for(control)` now permits explicit pump intents, plus light intents only
  with a capability descriptor explicitly reporting no dedicated circ pump.
- Require synchronized available state, operating byte0=0, priming byte1=1,
  notification byte18 in the recognized priming forms 0/2, and no existing
  lock/unknown-high-bit restrictions. Unknown modes/flags remain rejected.
- Keep capability/value validation, fresh pre-transmission state, one in-flight
  command, observed confirmation and all ordinary bus policies unchanged.
- Heating/range/session changes, settings, reminders, Hold, Soak, and Normal
  Operation are NOT enabled by this exception. Never automatically exit priming.
- Cancel pending intents when priming status changes. Priming-created intents
  also cancel across socket epochs, so reconnect cannot replay a manual priming
  goal. Preserve in-flight ambiguity tracking even when its goal is cancelled.
- Diagnostics now list `permitted_controls` separately from general readiness.

The rejected, unpublished six-minute reconnect heuristic and its tests/module
were removed. No new timer, reconnect reason or channel allocation was added.

## Tests and acceptance boundary

Before the admission correction, eight new tests failed, including native core
pump/light requests over real loopback TCP in classic, negotiated-channel and
explicit direct modes. The synthetic peer keeps reporting priming throughout;
no restart or status normalization is allowed to make the test pass.

Tests cover pump 0→1→2→0, light on/off, observed confirmation, stale-state denial,
existing locks/unknown flags, dedicated-circ light denial, heating denial and
pending/in-flight intent lifecycle across mode changes and reconnect.

A native HA light-service/diagnostics test is added for the Linux HA CI job.
Actual HA execution and hardware acceptance are separate gates. No production
commands, installation, restart, EW11 settings or automations changed here.

Local validation: 725 core tests passed with 97.02% branch-aware coverage.
Ruff lint/format, strict core typing, generated HACS bundle equality and whitespace
checks passed. Actual HA execution remains a required CI gate for this candidate.
