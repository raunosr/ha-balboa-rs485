# Local protocol laboratory

Phase 1 runs without Home Assistant or spa hardware, using Python 3.12+.
Install a supported Python first if `python` is not on PATH.

## Windows PowerShell

```powershell
python -m venv .venv
& .venv/Scripts/python.exe -m pip install -e '.[dev]'
& .venv/Scripts/python.exe -m tools.dev test
& .venv/Scripts/python.exe -m tools.dev lint
& .venv/Scripts/python.exe -m tools.simulator --scenario normal --port 8899
```

In a second terminal in the same repository:

```powershell
& .venv/Scripts/python.exe -m tools.smoke_client --host 127.0.0.1 --port 8899 --frames 6
```

This task used Codex's bundled Python to create `.venv` because system Python was
absent from PATH. The existing `.venv/Scripts/python.exe` commands work directly.

## Linux/macOS or activated venv

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
make test
make lint
make lab
# Second terminal, with the venv activated:
python -m tools.smoke_client --host 127.0.0.1 --port 8899 --frames 6
```

Make is optional: `python -m tools.dev test|lint|simulator|smoke|lab` provides the
same entry points. `lab` starts the simulator in the foreground and prints the
second-terminal command; Ctrl+C stops it. Ports are configurable, including 9999.
The simulator defaults to 127.0.0.1. Port 0 asks the OS for a free port; read the
printed bound port. Tests always bind ephemeral loopback ports.

## Failure scenarios

```sh
python -m tools.simulator --scenario bad-crc --port 8899
python -m tools.simulator --scenario partial-frame --port 8899
python -m tools.simulator --scenario garbage-before-frame --port 8899
```

Run one server at a time per port. Normal sends READY plus a static 27 C / 38 C
status each interval (default 1 s). Bad CRC injects a corrupt status before a
valid status each cycle. Partial-frame splits writes at deterministic boundaries;
TCP can still coalesce them, so parser unit tests separately prove every split.
Garbage-prefix injects known junk before the cycle. `--interval` and
`--fragment-delay` control simulator timing only; neither is bus synchronization.

Smoke is receive-only. `--frames` counts validated frames including unknown IDs;
0 watches until Ctrl+C. `--timeout` bounds connect and each wait for a valid frame,
even if junk/partial bytes arrive. Status-only traffic does not identify a write
protocol. Output says CONFIG pending; READY recognition is an observation only.
Exit 0: requested count reached/clean stream EOF; 1: network error or timeout;
2: invalid CLI input; 130: user interruption. A malformed known message increments
diagnostics; it is not itself a process failure. Frame RX counts include the whole
read batch, even if `--frames` stops display partway through that batch.
No `pump1 high` or setpoint interface exists before Phase 3.

The suite covers framing/decoding, real TCP scenarios, cleanup, client TX=0,
CLI errors, and dev commands. Tests never contact a LAN spa or public service.
The actual test and coverage report is in `docs/phase1_review.md`.

## Phase 2 transport lab

```powershell
& .venv/Scripts/python.exe -m tools.simulator --transport-lab --port 8899
# Second terminal:
& .venv/Scripts/python.exe -m tools.smoke_client --transport --mode classic-rs485 --duration 15
```

This simulator orders status before CTS and answers only known configuration
requests, enforcing at most one request per CTS cycle. The original default
passive fixture stream remains compatible with Phase 1 tools. Without an explicit
supported `--mode`, auto observes only and never sends. BWA mode is for an actual
Wi-Fi module, never a missing-CTS workaround on Elfin. Channel mode is unsupported
and passive. The hardware observation confirmed that distinction matters here.

Transport diagnostic exits 0 for current READY, or valid passive observations
when auto/channel was requested; 1 for unavailable explicit mode or no valid
frames; 2 for invalid options; 130 for interruption. It always closes its socket
at `--duration`. `--frames` belongs only to the original observer.

Transport scenarios: normal, slow-network, missing-ready, bad-crc, partial-frame,
garbage-before-frame, connection-reset, silent-zombie-socket, elfin-reboot,
configuration-change, unknown-protocol. Additional safety scenarios:
missing-configuration, channel-protocol, channel-after-sync. New scenarios enable
transport simulation automatically; use `--transport-lab` with the four original
scenario names. Reset/reboot/zombie faults start after four cycles on the first
connection; later connections recover. Configuration changes after four cycles,
detected at the next refresh (default 60 seconds). Timing is injectable in tests.

READY interval statistics measure local TCP arrival intervals, not physical bus
timing; batching can produce zero intervals. Traffic rate is a bounded 10-second
rolling window of 100 time buckets. Events and interval samples are bounded to
128. Configuration timeout retries are permitted; physical toggle retries are not
implemented in Phase 2 and must not be inferred from query behavior.

## Phase 3 command lab (numeric loopback only)

```powershell
& .venv/Scripts/python.exe -m tools.simulator --control-lab --port 8899
# Second terminal:
& .venv/Scripts/python.exe -m tools.smoke_client --mode classic-rs485 --interactive
```

Enter `pump1 high`, `target 39`, `light1 on`. `wait` waits for current requests;
`status` reads the current observed snapshot; `history` displays physical
transactions; `cancel pump1` cancels intent without forgetting a sent action;
`quit` or EOF closes the lab. Ctrl+C interrupts input without leaving a blocked
stdin executor thread. Every network operation remains asynchronous.

Scripted bursts use the same runtime, without an interactive console:

```powershell
& .venv/Scripts/python.exe -m tools.smoke_client --mode classic-rs485 --command 'target 35' --command 'target 39'
& .venv/Scripts/python.exe -m tools.smoke_client --mode classic-rs485 --demo rapid-pump-intent-changes
& .venv/Scripts/python.exe -m tools.smoke_client --mode classic-rs485 --demo rapid-setpoint-changes
```

Rapid scenario names can also be selected on the simulator; their wire behavior
is normal. The matching client `--demo` supplies the burst of desired values.
A server cannot generate client intent, and these scenarios do not inject a raw
toggle sequence. Defaults start at 38 C, so the temperature burst ends at 39 C to
exercise one physical write rather than a no-op. The pump burst ends at LOW.

For the mandatory failure case, restart the simulator with:

```powershell
& .venv/Scripts/python.exe -m tools.simulator --control-lab --scenario lost-status-after-command --interval 0.5
# Second terminal:
& .venv/Scripts/python.exe -m tools.smoke_client --mode classic-rs485 --command 'pump1 high' --timeout 20
```

The first toggle changes the synthetic pump to LOW but all subsequent status in
that socket epoch is withheld (CTS continues). Client confirmation times out,
reconnects/reloads configuration, observes stable LOW, then sends one new toggle
for HIGH. Desired LOW would finish with exactly one physical command total.
`reset-after-command` tests abrupt loss after application. `single-speed-pump`
reports ON as raw 2; use `pump1 on` / `pump1 off`. `accessories` advertises agreed
light 2, aux and mister mappings. `missing-metadata` leaves supplemental values
unknown; `metadata-change` injects a later fault observation.

The simulator is synthetic and does not model actual electrical CTS timing,
controller safety interlocks or thermal dynamics. Requests
to LAN addresses are rejected by the command CLI before opening a socket.
Session restart tests are included in Phase 5; thermal dynamics remain out of scope.

## Phase 4 — channel and real Home Assistant tests

`python -m tools.simulator --channel-lab --port 8899` models correlated channel
allocation, addressed configuration/control traffic and idle replies. It is not
proof of real-controller compatibility. Do not point a control lab at the Elfin.

Core tests/lint still run locally on Windows. For actual Home Assistant testing,
use Linux with Python 3.14.2+ (CI uses 3.14); do not install HA into the Python 3.12
core environment:

```sh
python -m pip install -e '.[dev]' -r requirements-ha-test.txt
python -m pytest tests_ha --ignore=tests_ha/test_installation.py -q --timeout=30 --cov --cov-config=tests_ha/coverage.ini
python -m pytest tests_ha/test_installation.py -q --timeout=30
python -m mypy custom_components/balboa_rs485 --follow-imports=silent --python-version 3.14
```

Run installation testing in a separate pytest process: it builds/extracts the ZIP,
loads the extracted integration through HA's real loader and requests the original
local icon from HA's authenticated brand endpoint. Other tests must not pre-import
the checkout adapter in that process. Its HTTP test narrowly ignores aiohttp's
`NotAppKeyWarning` because HA 2026.8.3 itself retains `app["hass"]` compatibility;
all other configured warnings remain errors.

The adapter has its own branch-aware 95% coverage gate. Only its mechanically
generated `_core` copy is omitted there; canonical core/tools coverage has a
separate 95% gate, and `python -m tools.package --check` enforces byte equality.

## Phase 5 — durable heating sessions

`tests/test_session.py` covers immutable intent and strict storage validation;
`tests/test_session_time.py` covers duration, explicit offsets, local deadlines and
Helsinki DST gaps/folds. `tests/test_session_runner.py` runs the actual runtime and
loopback simulator with only clock and persistence boundaries substituted. It
checks expiry, delayed/interrupted/failed storage, concurrent starts, manual
abandonment, disabled controls, panel changes, lost confirmation, restart and
pre-transmission deadline admission. No HA imports are needed for these tests.

`tests_ha/test_sessions.py` covers real HA actions, Store, entity state and entry
lifecycle on 2026.8.3. The separate extracted-ZIP test also starts/cancels a session
and observes `holding` and `idle` from the installed package. These tests do not
contact the user's HA server or physical spa.
