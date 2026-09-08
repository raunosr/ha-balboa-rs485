# Home Assistant — experimental package

Current native controls, profile-aware bathing sessions, filter schedules and
diagnostics: [0.0.14 guide](native_controls_0_0_13.md). Read
[Phase 4B acceptance](phase4b_review.md) for actual installation/hardware results.
The Phase 4/5 sections below describe the retained foundation and legacy same-range
session action, not the complete current feature inventory.

Target: **Home Assistant 2026.8.3 or newer**. Actual adapter tests run against
2026.8.3 in Linux CI using Python 3.14. This is an experimental custom integration,
not the official Home Assistant Balboa integration or a Balboa vendor product.
Phase 5 adds heating sessions to the simulator-backed Phase 4 adapter. Install/test
against the simulator first. Real-gateway negotiation and controls still need separately
coordinated validation; this is not a claim of production hardware readiness.

## Packaging and privacy

Use [HACS installation](hacs_installation.md) for the public
`raunosr/ha-balboa-rs485` source. Earlier development history is retained privately;
the public repository starts from a sanitized snapshot. It is a HACS custom
repository, not a default-catalog listing. No Home Assistant brands submission is
needed for the bundled local icon on supported HA versions.

The manual installation archive contains
`custom_components/balboa_rs485/`. It is self-contained: the independent Python
core is bundled in `_core`, with no private pip dependencies. Developers change
the canonical root `balboa_rs485/` and regenerate the bundle:

```powershell
& .venv/Scripts/python.exe -m tools.package
& .venv/Scripts/python.exe -m tools.package --check --zip dist/balboa-rs485.zip
```

CI checks byte equality between the canonical and bundled core. The ZIP builder
sorts entries and fixes timestamps/permissions for reproducibility. Development
files, local captures and virtual environments are not included.

The original icon is installed as `brand/icon.png` using HA's
[local custom-integration branding](https://developers.home-assistant.io/docs/core/integration/brand_images/).
See `branding.md` for the image-generation prompt and provenance.

## Manual installation

1. Preserve the previous component directory for rollback. Use the reviewed
   `balboa-rs485-0.0.14.zip` artifact with its documented acceptance limitations,
   not GitHub's whole-source ZIP.
2. Extract its `custom_components/balboa_rs485` directory under the HA
   configuration directory. The resulting path is
   `<config>/custom_components/balboa_rs485/manifest.json`.
3. Restart Home Assistant. Open **Settings → Devices & services → Add integration**
   and search for **Balboa RS485**.
4. First test with the simulator reachable from HA. Enter its host/port and
   `classic-rs485` when running the simulator with `--control-lab`.
5. For a separately coordinated real-gateway check, stop competing clients and
   begin with `auto`. Leave physical controls disabled. The user's Elfin has
   observed channel traffic: **do not select classic-rs485 for it**.

On a separate HA machine, `127.0.0.1` refers to that HA machine, not the development
PC. Do not expose the simulator or gateway to the public Internet. No MQTT broker,
Docker add-on or private Python package download is required by this integration.

To update, stop/unload this integration first, back up its existing directory,
replace only `custom_components/balboa_rs485` with the reviewed package and restart
HA. Preserve the existing config entry. To remove it, remove the entry through HA,
then remove only that integration directory and restart. Do not delete the whole
`custom_components` directory.

## Connection choices

For the tested gateway configuration and weak-WLAN measurements, see
[EW11 settings](ew11_settings.md). The current device-page gaps versus the user's
old MQTT integration are tracked in [native entity coverage](entity_parity.md).

Use only one integration entry per physical controller. Stop BWAlink and other
clients before testing the gateway. Ports are configurable; 8899 is just a default.

| Mode | Meaning |
| --- | --- |
| auto | Passive observation; no guessed channel or outgoing query/control |
| unknown-read-only | Explicit passive observation |
| channel-rs485 | Experimental correlated channel assignment and owned CTS |
| classic-rs485 | Explicit classic bus; never select merely because TCP connects |
| bwa-tcp | Actual BWA Wi-Fi module only; **not** raw Elfin RS485-over-TCP |

Opening the configuration form sends no traffic. Submitting it opens a temporary
read-only connection and requires a valid standard Balboa status. The long-lived
runtime then owns one connection and synchronizes configuration in a supported
explicit mode. A TCP socket or a valid status alone does **not** make controls
available. Physical state is always observed, never updated optimistically.

Channel assignment is bounded to three requests per runtime and one per socket.
A gateway echo or client message on the assigned address blocks writes. Reloading
starts a new runtime, so do not repeatedly reload an incompatible channel bus:
controller channel allocations may be finite. Short channel/hardware acceptance
is recorded in the reviews; long-duration allocation recovery remains open.
In channel mode, missing status at startup keeps the same runtime and its request
budget, with physical entities unavailable. It does not trigger repeated HA setup
attempts that would each receive a fresh allocation budget. The diagnostic
connection sensor remains visible.

Entities/device identity is scoped to HA's persisted config-entry identifier.
The model, IP address and configuration signature are not unique hardware IDs.
Use the entry's Reconfigure menu to change the endpoint while preserving the same entry; deleting and
recreating the entry necessarily creates a new identity.

## Native controls

| Entity | Mapping |
| --- | --- |
| Climate | Observed water/target temperature, heater action, setup-derived bounds; no fake power-off |
| Pump fans | Single speed: off/on; two speeds: 0/50/100 percent |
| Blower fan | Percentages map upward to the supported discrete speed |
| Lights | On/off only; no invented brightness or color capability |
| Auxiliary/mister switches | Added only when a consistent capability descriptor supports them |
| Connection sensor | Diagnostic state and protocol reason remain visible when the spa is unavailable |
| Heating session sensor | Durable session phase, UTC start/end times, desired temperatures/unit and blocked reason; visible offline |

All physical controls start disabled. Integration **Configure** options enable
them without reconnecting. Disabling controls cancels outstanding remaining goals;
an already transmitted physical step cannot be undone or assumed not to have run.
Commands wait for observation-based verification and report failures to HA.
Entities never display a desired value as if it were an observed physical value.

An unsupported accessory is omitted. A previously known accessory whose capability
disappears remains registered but unavailable, preserving its identity and history.
Full fault events, writable clock/filter schedules and additional status mappings
are outside this basic Phase 4 package; no continuous fault monitoring is claimed.

## Diagnostics

The integration's **Download diagnostics** report includes connection health,
relative frame/status/CTS ages, recoveries, protocol mode, configuration metadata
and a bounded recent command history with verification latency. Host, port and
configuration signature are redacted. Arbitrary entry fields and raw frames are
never serialized. Diagnostics still describe observations and do not prove real
hardware compatibility.

## Heating sessions (Phase 5)

Open **Developer tools → Actions** and select one of the integration's actions.
The Spa selector chooses the loaded Balboa config entry; no entity identifier or
gateway address is needed in the action data.

| Action | Inputs and effect |
| --- | --- |
| `balboa_rs485.start_heating_session` | Required target/maintenance temperatures and either `duration` or `end_time`; begins immediately |
| `balboa_rs485.extend_heating_session` | Add `duration` to an active deadline; defaults to 30 minutes |
| `balboa_rs485.reduce_heating_session` | Subtract `duration`; defaults to 30 minutes; reaching the deadline starts restoration |
| `balboa_rs485.cancel_heating_session` | Request maintenance restoration, including when currently offline |

Example action YAML (select your integration entry in the UI):

```yaml
action: balboa_rs485.start_heating_session
data:
  config_entry_id: YOUR_BALBOA_ENTRY_ID
  target_temperature: 38
  maintenance_temperature: 27
  temperature_unit: C
  duration: "10:00:00"
```

Duration includes preheating. Alternatively use `end_time: "18:00"` for the next
local occurrence, or an ISO datetime including an explicit UTC offset. A DST-gap
or ambiguous local clock time is rejected; use an explicit offset instead. Do not
provide both duration and end time. Temperatures must match the spa's unit (`C`
by default, or explicitly `F`), observed range and supported step. The integration
does not switch range, unlock the panel, or change the heating mode for a session.

Only one session can be active. Its sensor reports `preheating`, `target_reached`,
`holding`, `restoring`, then `idle`. These describe intent and observations, not
an optimistic heater state. Actual water temperature, setpoint and heater activity
remain on the climate entity. A completed action means the intent was accepted
and persisted; use the sensor and observed climate state to confirm execution.

A manual HA climate setpoint durably abandons the session before applying the new
temperature. Invalid manual input does not abandon it. A physical-panel change is
reported as `setpoint_changed` without repeatedly overriding it; adjustment/cancel
or reconnection re-evaluates the session. Expired/cancelled sessions cannot be
extended back into heating.

The session survives reload/restart. Expiry is checked before any restored target
request. If HA, the network or the spa is unavailable, it cannot physically lower
the setpoint: `restoring` waits for enabled controls and fresh safe observations.
There is **no timer programmed into the spa**. Cancel and confirm maintenance
before stopping HA if restoration must happen during the shutdown.

Intent is stored privately and atomically in HA Store, bound to this entry's
connection settings. Unload preserves it; entry removal deletes only that entry's
record and does not send maintenance commands. Cancel and confirm restoration
before removing or reconfiguring an active entry.

`blocked_reason` explains waiting: `controls_disabled`, `unavailable`,
`waiting_for_verification`, `unsupported_state`, `setpoint_changed`,
`command_failed`, or `storage_error`. A storage error blocks session writes; check
HA logs, disk space and permissions, then reload after repair. Do not blindly erase
the record: an existing heating setpoint may still be active. An endpoint mismatch
also blocks restoration to the new endpoint; restore the original connection or
resolve the old spa's setpoint manually before deleting the entry. Never edit Store
while HA is running.

Prediction, energy and custom cards remain outside Phase 5.
