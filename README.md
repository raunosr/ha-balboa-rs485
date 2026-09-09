# Balboa RS485 for Home Assistant

<img src="custom_components/balboa_rs485/brand/icon.png" width="128" alt="Original Balboa RS485 spa icon">

Native, local Home Assistant integration using an Elfin EW11/EW11A raw TCP bridge.
**Experimental release 0.0.19.** Native observations, controller diagnostics,
a discrete Pump 1 speed slider, Low/High profiles, two filter schedules with start/end time
controls, and durable bathing sessions with a 36.5 C default minimum are implemented.
Supported pumps, blower, lights and accessories are discovered from the controller;
absent hardware is not represented by invented sensors. Changes are verified from
observed spa state, never optimistic toggles.
See the [native controls guide](docs/native_controls_0_0_13.md) for behavior and
the [Phase 4B review](docs/phase4b_review.md) for laboratory versus hardware evidence. The
[prediction guide](docs/heating_prediction.md) explains the five forecast sensors,
initial learning, optional outdoor temperature and error metrics.

**Not yet a fully accepted BWALink replacement.** Bounded light/pump tests have
passed, including Pump 1 high-to-low on 0.0.14 and filter readback/restoration on
0.0.15. Low-to-High and negotiated-channel recovery did not pass on that version. Version 0.0.16
adds an explicitly selected **Direct RS485/TCP – fixed address (experimental)**
mode for supervised compatibility trials. It does not reserve a channel or wait
for CTS, so collisions with the panel remain possible; it is never an automatic
fallback. Risk acceptance and stopping other network clients are required.
See the [direct-mode trial review](docs/direct_tcp_live_review.md).
Its bounded real-spa light and High/Low restoration tests passed, including two
automatic recoveries after unconfirmed commands; first-attempt reliability is
not established. The trial used one HA restart and preserved all 54 entity IDs.
Other advanced controls and long-duration weak-network recovery still need
hardware acceptance. Negotiated mode retains its finite three-allocation budget.
No automation migration is performed.
An offline HA cannot restore a bathing session until it returns; the timer is not
stored in the spa. Do not use experimental controls unattended.

See the [0.0.15 filter confirmation review](docs/filter_confirmation_review.md)
for reproducible laboratory failures, the scoped correction and remaining gates.

0.0.17 corrects command admission during known maintenance reminders and makes
connection cleanup independent of entity-platform unload success. Historical log
entries are labelled explicitly and retained across connection gaps. It does not
establish the cause of a reported whole-HA crash. See the
[reliability review](docs/reliability_0_0_17.md) for tests and remaining limits.
The 0.0.17 bounded native-control test and normal entry reload passed with settings
restored, but one command needed automatic recovery. Global clock Activity noise
can be filtered; the device-specific view requires a separate history-retention
choice. This remains experimental, not a claim of unattended reliability.

0.0.18 treats unrecognized maintenance-range reminder codes (such as code 2)
as `none` without blocking ordinary controls, while preserving the raw code in
diagnostics. Priming, operating-mode, fault-code and lock guards remain active.
Acknowledgement applies to one known reminder, not the whole queue; ambiguous
acknowledgements are never automatically repeated. See the
[reminder acknowledgement review](docs/reminder_ack_review.md) for this explicit
compatibility policy and its tests.

0.0.19 makes Pump 1's default control a **0 / 1 / 2 slider** (off / circulation /
jets on two-speed pumps). The old fan/select IDs remain usable but are hidden once;
you may unhide them. When the spa requires automatic circulation, select **1** to
stop jets: the integration cannot force circulation off. Same-speed requests share
one bounded command; a retained LOW response no longer starts a retry/reconnect loop.
Heating policy stays Rest during temporary Ready-in-Rest, while the mode sensor
shows the actual transient state. See the [correction and limits](docs/pump1_circulation_review.md).

Target Home Assistant **2026.8.3+**, tested on 2026.8.3. Read the
[installation and safety guide](docs/home_assistant.md) before connecting.
Install through HACS as a **custom integration repository**; it is not in HACS's
default catalog. See [HACS installation](docs/hacs_installation.md). The original
icon is bundled locally. Installing/downloading is separate from physical acceptance.

The public repository starts from a reviewed source snapshot. Earlier private
development history and its CI links are preserved in a separate private archive;
historical review documents are not current production-state assertions.

The standalone core requires Python 3.12+. No runtime dependencies, MQTT, Docker,
cloud, Home Assistant or spa hardware are needed for core development.

```sh
python -m pip install -e '.[dev]'
python -m tools.dev test
python -m tools.dev lint
python -m tools.simulator --scenario normal --port 8899
# In a second terminal:
python -m tools.smoke_client --host 127.0.0.1 --port 8899 --frames 6
```

See [local testing](docs/local_testing.md) for Windows, virtual environments,
failure scenarios and `make` equivalents. Start with [architecture](docs/architecture.md),
[implementation plan](docs/implementation_plan.md), and [protocol sources](docs/protocol_sources.md).
[Hardware validation](docs/hardware_validation.md) includes a short passive Elfin
check. Short target/session tests passed on 0.0.9; long-duration recovery/soak
remain open. See [hardware acceptance](docs/bp6013_compatibility_review.md).
GitHub repository: [`raunosr/ha-balboa-rs485`](https://github.com/raunosr/ha-balboa-rs485).
See [contribution rules](CONTRIBUTING.md) and [security reporting](SECURITY.md).
Released under the [MIT License](LICENSE). Independent community software;
not affiliated with or endorsed by Balboa Water Group or Home Assistant.

For the Phase 2 loopback lab, add `--transport-lab` to the simulator and use
`--transport --mode classic-rs485 --duration 15` in the smoke client. This only
sends known configuration queries. Default `auto` is passive: overlapping CTS
signatures cannot establish ownership. Experimental correlated channel negotiation
is implemented and simulator-tested in Phase 4; short Elfin/BP6013G2 acceptance is
recorded for 0.0.9, with a remaining long-duration allocation-budget limit. See
[Phase 2 review](docs/phase2_review.md) and [design](docs/phase2_design.md).

## Observation-verified command lab

```sh
python -m tools.simulator --control-lab --port 8899
# Second terminal (numeric loopback only):
python -m tools.smoke_client --mode classic-rs485 --interactive
```

Try `pump1 high`, `target 39`, `light1 on`, `wait`, `history`, `quit`.
Desired values coalesce; one physical step is sent per fresh CTS, then verified
from incoming status. Lost confirmation requires resynchronization, not blind
toggle replay. Earlier physical target/session tests and bounded light/Pump 2/3
tests passed; advanced controls remain separately hardware-unvalidated. Read the
[Phase 3 safety policy](docs/phase3_design.md), [review](docs/phase3_review.md),
and [local test recipes](docs/local_testing.md).
