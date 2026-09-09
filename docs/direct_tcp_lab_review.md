# Direct RS485/TCP fixed-address laboratory experiment

Status: implemented locally; no HA installation, release or hardware acceptance.
The user authorized the laboratory continuation and requested technical names for
connection modes, rather than another application's name.

## Names and scope

| Mode ID | Meaning |
| --- | --- |
| `auto` | Passive detection; no automatic transmission-mode selection |
| `unknown-read-only` | Read-only observation |
| `bwa-tcp` | TCP to the Balboa Wi-Fi module, which arbitrates its downstream bus |
| `classic-rs485` | CTS-controlled RS485, fixed source address |
| `channel-rs485` | RS485 with negotiated channel ownership and addressed CTS |
| `direct-rs485-tcp-lab` | Direct RS485/TCP, fixed address, experimental loopback only |

The Finnish name is **Suora RS485/TCP – kiinteä osoite (kokeellinen)**. Existing
mode IDs and behavior are unchanged. The new mode is excluded from HA configuration
and rejected by the core for every host except literal `127.0.0.1` and `::1`.
Do not bypass this boundary with a forwarding tunnel or a live-device proxy.
BWALink is a source reference only; see `bwalink_transport_review.md`.

## Design and limitations

The synthetic peer accepts fixed-address 0x0A writes without CTS even when its
negotiated-channel pool is exhausted. This is an explicit experimental premise,
not evidence that a real controller will accept those writes or avoid collisions.
Complete receive batches permit at most one write per 100 ms, a lab anti-burst
policy rather than a bus timing guarantee. The mode is never an automatic fallback.

The existing runtime still requires synchronized configuration and fresh observed
state. EOF/silence closes the old socket, applies backoff and resynchronizes in a
new epoch, with zero allocations. Physical confirmation, locks, bounded histories
and no replay of raw toggles remain unchanged. Direct transactions do not claim a
CTS timestamp. Alternative protocol families or observed unidirectional messages
from another sender/echo at 0x0A inhibit writes for the epoch. That inhibition is
fail-closed, not advertised as recovery from an active competing writer.

Tests initially failed before the mode existed. Six command tests then exposed an
incorrect collision check against bidirectional BF23 filter data. A focused policy
test reproduced it; normal queried filter responses no longer trigger that check.
This was a laboratory implementation defect, not a diagnosed production failure.

## Verified behavior

The latest focused run passed **21 tests in 7.86 seconds** (18 direct-mode tests
and three existing bus-policy tests): repeated connection losses beyond three,
silent zombie recovery, High/Low and pump confirmation loss/reset, delayed replies
and commit without optimistic state, single active socket, cancellation, pacing,
unsupported-family/echo inhibition, and rejection of remote endpoints. Broader
core and HA validation must be recorded separately; this is not hardware acceptance.

On 2026-09-09 the complete local core/tools suite passed **566 tests in 63.77s**,
with **97.04% branch-aware coverage**. Ruff lint/format, strict core typing,
bundled-core equality and whitespace checks passed. A durable JUnit report is
retained privately; interrupted earlier full runs are not counted as passes.
The separate Linux/Home Assistant job is reported by the review branch's CI;
local core results do not substitute for that job or physical acceptance.

No production HA setting, restart, physical command or automation was changed.
Promotion requires an explicit live-trial risk review, single-writer verification,
bounded commands and independent readback. No new HA restart allowance exists.
