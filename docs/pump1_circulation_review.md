# Pump 1 circulation and native control correction

## Scope and evidence

Version v0.0.19 addresses three reproduced v0.0.18 symptoms: duplicate same-speed
HA requests reporting SUPERSEDED, repeated attempts to switch Pump 1 OFF while
the controller keeps LOW running, and Heating policy becoming unknown during
Ready-in-Rest. It does not claim to eliminate packet loss on an RS485/TCP bridge.

The [Balboa TP600 guide](https://www.balboawater.com/wp-content/uploads/2025/02/TP600-User-Guide-English.pdf),
printed pages 4 and 6, describes non-circulation systems using Pump 1 LOW when
another pump/blower runs and for automatic heating/filtering/polling. Automatically
started LOW cannot be stopped from the panel. Ready-in-Rest is temporary heating
triggered by Jets 1 while the selected policy remains Rest. These are controller
behaviors, not evidence that every failed OFF command is a network failure.

The local reproducer shows LOW plus another pump ON planning a LOW -> HIGH step
for an impossible OFF goal. Duplicate native fan/select requests replace the
same goal; the first caller receives SUPERSEDED. Actual Heating mode already
reports ready_in_rest correctly, but the policy selector formerly returned None.

## Changes

- Pump 1 has one default numeric slider: 0 OFF, 1 circulation, 2 jets for a
  two-speed capability; a single-speed Pump 1 has 0/1. Values are actual observed
  states, never optimistic or restored output commands.
- Existing Pump 1 fan and select IDs remain enabled service targets. They are
  hidden once, using the entity registry, not deleted. User unhiding is preserved
  on later reloads. Other pumps are unchanged. No automation migration occurs.
- Identical overlapping native pump requests join the same intent with its
  original deadline and action budget. Cancelling one caller does not cancel a
  remaining caller; last-caller cancellation, disable and unload still cancel.
  Different requested speeds still supersede; reminder/session guards are unchanged.
- With an explicitly known two-speed/non-circulation capability, observed other
  pump/blower activity, heating, Ready-in-Rest below the observed target, or agreed
  filter flags inhibit OFF. Ready-in-Rest alone does not block OFF once the target
  is reached; unknown temperatures do not invent a circulation requirement.
  Select 1 to stop jets without fighting automatic circulation. No unknown bit
  layout, temperature polling or cleanup flag is invented. The slider exposes
  a circulation reason when positively inferred; absence is unknown, not proof
  that circulation can be stopped.
- A fresh guarded HIGH -> LOW response to OFF ends that goal as FAILED with a
  clear circulation explanation, while retaining the connection. It is not
  reported as OFF or VERIFIED. The engine does not cycle LOW -> HIGH again.
  An unchanged/unavailable/stale/unsafe response retains normal ambiguity recovery.
- Heating policy maps Ready-in-Rest to Rest without sending anything. The separate
  Heating mode sensor preserves the actual ready_in_rest observation. Truly
  unknown mode bytes remain unknown.

## Verification and acceptance

Targeted core regressions first failed on the original behavior. Candidate
checks cover retained LOW, existing post-send/epoch protections, queued revalidation,
different final goals and continued unrelated commands. TCP tests exercise classic,
channel-arbitrated and explicit direct modes. Real HA framework tests cover native
service aliases, cancellation, original deadlines, slider steps and entity migration.

Both final CI runs passed 673 core tests, 109 HA tests, isolated ZIP installation,
HACS validation, lint and strict typing. The owner manually merged PR11; the merged
source tree exactly matched the tested candidate. HACS installed v0.0.19, and the
owner performed the one activation restart after the restart tool rejected dispatch.
Loaded manifest version and all 54 existing entity IDs were verified; the new slider
is the 55th entity. Old Pump 1 fan/select aliases are hidden, not disabled or removed.

Bounded native hardware acceptance on the two-speed/non-circ BP6013G2 passed:

- Pump 1: 0 -> 1 -> 2 -> 1 -> 0, then 0 -> 2 -> 0.
- Light: OFF -> ON -> OFF.
- Temperature target: one half-degree step and restoration of the observed baseline.
- Ready-in-Rest remained visible in Heating mode while Heating policy stayed Rest.

The ten goals produced 13 transmissions, all verified (mean confirmation 0.34 s).
The connection remained READY in the same epoch, with no added recoveries or failed
transactions during this trial. A recovery recorded before the trial is not erased
or attributed to it. This is bounded acceptance, not a long-duration reliability claim.
After the target writes, Pump 1 LOW was observed again without a new pump goal;
the controller's automatic circulation cannot be uniquely identified from these bits.
LOW subsequently returned to OFF without another command. Final readback confirmed
Pump 1 OFF, original target restored and connection READY; light and the other
pumps had been verified OFF. Heating policy remained Rest while the transient
Ready-in-Rest mode was not forcibly cleared. No fault injection, automation
migration, EW11 setting change, or further HA restart was performed.

The subsequent user trial did reproduce confirmation timeouts and replaced-goal
notices. The short passing sequence above is not general reliability acceptance.
See `command_lifecycle_review.md` for the measured boundary and lab follow-up.
