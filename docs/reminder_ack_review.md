# Reminder acknowledgement investigation — 2026-09-09

Status: 0.0.18 published through PR10 and activated through HACS on 2026-09-09.
Bounded native-control acceptance completed; first-attempt reliability remains
limited. See the activation evidence below.
The meaning of notification code 2 remains unverified. Following the incident,
the owner explicitly selected a non-blocking `none` compatibility default for
unknown reminders and authorized HACS installation with one HA restart.

## Observed incident and limits

Installed v0.0.17 sent one BF11 item 03 after the owner pressed Acknowledge
reminder. The status changed from reminder code 3 to unrecognized code 2.
The four-second confirmation deadline expired, recovery opened a new epoch,
and the epoch-bound caller guard cancelled the intent. The fresh connection
was READY, but normal controls were blocked by `unsupported_notification_2`.
This is not evidence of a socket deadlock or an HA Core crash.

The owner subsequently reported no message on the physical panel. Recorder
later showed a transition from code 2 to normal/no-reminder state, without any
additional acknowledgement or restart performed by this agent. Thus a queued
maintenance reminder is a useful reproduction scenario, not a proven meaning
for this controller's code 2. No new physical spa command was used to reproduce
the acknowledgement incident.

## Source comparison

BWALink's [Dockerfile](https://github.com/jshank/bwalink/blob/bab3dea3a667908a691326976c60522824c00efb/ha-addon/Dockerfile)
installs the `balboa_worldwide_app` Ruby gem without a version pin. The locally
reviewed [status decoder](https://github.com/ccutrer/balboa_worldwide_app/blob/a9031c7c4b3060ecb093f1c74ee42b45ef89934c/lib/bwa/messages/status.rb)
maps only 0 (none), 4 (filter), 9 (sanitizer) and 10 (pH). Code 2 is absent.
Its [MQTT bridge](https://github.com/ccutrer/balboa_worldwide_app/blob/a9031c7c4b3060ecb093f1c74ee42b45ef89934c/exe/bwa_mqtt_bridge)
publishes unrecognized/nil notifications as `none`; that does not establish
the code's real meaning. This is a pinned source inspection, not a claim about
the exact gem version inside the owner's installed add-on image.

The [protocol wiki](https://github.com/ccutrer/balboa_worldwide_app/wiki)
documents clear-notification item 03 and the notification flag fields, but no
meaning for reminder code 2. Balboa's
[TP700 manual](https://www.balboawater.com/wp-content/uploads/2024/12/TP700-user-guide_42370-rev-A_English.pdf)
describes individually resettable maintenance messages; it does not resolve
code 2. No third-party code was copied.

## Deterministic reproduction and correction

The loopback simulator can now present a second reminder after an acknowledgement.
Before the correction, both 3 -> 4 (known) and 3 -> 2 (unknown) reproduced the
same timeout/recovery/CANCELLED chain on repeated runs. Merely replacing the
next code with another known code did not avoid the failure, separating the
confirmation bug from the unknown-code admission guard.

An acknowledgement intent now captures the displayed reminder code. Fresh,
same-epoch transition to no reminder or a different **known routine** reminder
verifies that one action. It never requires clearing the entire queue. A reminder
that changes before transmission cancels the queued action. An ambiguous sent
acknowledgement is terminal FAILED, with an explicit "not retried" reason,
including after reconnect; ordinary desired-state recovery is unchanged.
Fault, lock and unsupported notification-flag transitions are not treated as
acknowledgement success.
Diagnostics include the requested reminder code for transaction interpretation.

## Owner-selected compatibility default

With initialization mode 3 and notification byte 18 exactly 1, unrecognized codes
below 15 display as `none` and no longer block normal controls. The upper bound
is a conservative policy boundary before fault-code space, not a newly decoded
meaning for each value. Code 2's meaning remains unknown. Codes 15 and above,
including unknown codes in that space, remain guarded, as do priming, Hold,
test/unknown operating modes, stale data and locks. No packet format or bus
ownership behavior changes.

Raw reminder codes and whether the fallback was used remain in diagnostics,
together with both notification flag bytes. An ignored reminder is not sent a
clear command: the acknowledgement button is a no-op in that state. A known
reminder changing to the non-blocking `none` state completes that one action.

Regression coverage includes real TCP acknowledgement followed by another
control, lost confirmation/reconnect, pre-send replacement, fault/lock guards,
and a real HA button -> climate -> light service sequence. All fault-history
records and unacknowledged remaining reminders must be preserved.

## Remaining boundary

This fixes both the reproduced queue/confirmation defect and code-2-only control
blocking under the selected policy. It does **not** identify code 2 or disable
actual operating-state protections. Real HA regressions exercise button -> code
2 -> climate -> light in classic RS485 and explicit direct RS485/TCP modes,
alongside retained fault protection and recovery. Production now runs v0.0.18.
The latest explicitly renewed one-restart grant was consumed by one accepted
normal HA Core restart. Energy work, Recorder
changes and automation migration remain deferred.

## HACS activation and bounded acceptance

PR10 was merged at `6fa538315e3fa74311cc599b3ce4f85ae4ca47db`; prerelease
`v0.0.18` was downloaded through HACS. Both the on-disk manifest before restart
and the loaded integration diagnostics after restart identify 0.0.18. All 54
pre-existing entity IDs were preserved. Configuration validation passed; the
other bridge application was confirmed stopped before and after the trial.

The four native service intents were temperature up by 0.5 C, restore its
original target, light on, and restore light off. All four reached VERIFIED
against fresh controller observations. The first and third completed on the
first transmission. Target restoration required two confirmation-timeout
recoveries; light restoration required one. Thus this is four completed intents
over seven transmissions, not seven successful commands or first-attempt
reliability acceptance. The recovery was autonomous, with no repeated manual
service request, integration reload or additional HA restart.

Final observations were READY with fresh status, controls enabled and safe,
no active priming/Hold/reminder, no blocked session, and restored target/light.
The recovery count remained three during the final read-only follow-up. The
Balboa-filtered system-log query contained no entries; this does not erase the
three transaction timeouts visible in integration diagnostics.

No physical acknowledgement was pressed and no reminder/fault was injected into
production. Code 2 was absent during the live trial: its non-blocking policy is
covered by deterministic core and HA framework tests, not a new physical code-2
reproduction. The 53 targeted reminder regressions passed again during startup.
The full candidate checks already passed 657 core tests, 102 HA tests, isolated
installation, HACS validation, lint and typing. Long-duration reliability and
other advanced controls remain outside this bounded acceptance.
