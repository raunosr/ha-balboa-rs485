# Reminder acknowledgement investigation — 2026-09-09

Status: laboratory correction, not a new release or installed production fix.
The meaning of notification code 2 remains unverified. Do not label it as a
maintenance reminder or relax its control guard solely from its numeric value.

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
Fault, lock and unknown transitions are not treated as acknowledgement success.
Diagnostics include the requested reminder code for transaction interpretation.

Regression coverage includes real TCP acknowledgement followed by another
control, lost confirmation/reconnect, pre-send replacement, fault/lock guards,
and a real HA button -> climate -> light service sequence. All fault-history
records and unacknowledged remaining reminders must be preserved.

## Remaining boundary

This fixes the demonstrated known-reminder queue/confirmation defect and
improves the bounded error path. It does **not** identify code 2 or claim that
all notification-dependent control blocking has been fixed. Production remains
v0.0.17 until a separately recorded HACS activation. No restart allowance was
consumed by this investigation; 1 of the current 2 remains. Energy work and
automation migration remain deferred.
