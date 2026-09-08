"""Supplemental observations do not invent model support or resolve disputed bits."""

from dataclasses import replace

import pytest

from balboa_rs485.protocol.frames import Frame
from balboa_rs485.protocol.messages import decode_message
from balboa_rs485.runtime import SpaRuntime
from balboa_rs485.transport.policy import Mode
from tools.simulator.server import Simulator

from .test_connection import FAST
from .test_state import observed


@pytest.mark.parametrize(
    "flags,result",
    [
        (3, (False, False)),
        (7, (None, False)),
        (11, (None, None)),
        (15, (True, None)),
        (31, (True, True)),
    ],
)
def test_filter_flags_are_known_only_where_both_documented_layouts_agree(flags, result):
    state = observed()
    raw = bytearray(state.status.frame.payload)
    raw[9] = flags
    status = decode_message(Frame(255, 175, 19, bytes(raw)))
    assert status.filter_running_consensus == result


@pytest.mark.parametrize(
    "flags,result",
    [(3, (False, False)), (7, (True, False)), (11, (False, True)), (15, (True, True))],
)
def test_bp6013_profile_uses_observed_cycle2_layout_and_pinned_cycle1_mapping(flags, result):
    raw = bytearray(observed().status.frame.payload)
    raw[9] = flags
    status = decode_message(Frame(255, 175, 19, bytes(raw)))
    assert status.filter_running_for_model("BP6013G2") == result
    assert status.filter_running_for_model("UNKNOWN") == status.filter_running_consensus


@pytest.mark.parametrize(
    "caps,present",
    [(b"\x06\0\x01\x82\0\0", True), (b"\x06\0\x01\x42\0\0", False), (b"\x06\0\x01\x02\0\0", False)],
)
def test_circulation_presence_requires_agreed_descriptor(caps, present):
    assert observed(capabilities=caps).has_circulation_pump == present


@pytest.mark.parametrize(
    "count,code,name",
    [(0, 0, "none"), (1, 17, "flow_failed"), (1, 27, "heater_dry"), (1, 255, "unrecognized")],
)
def test_fault_name_is_historical_and_retains_unrecognized_code(count, code, name):
    message = decode_message(Frame(10, 191, 40, bytes((count, 0, code, 2, 12, 30, 0, 76, 72, 72))))
    assert message.name == name
    assert message.code == code


async def test_periodic_metadata_refresh_observes_new_fault_without_new_socket_or_physical_write():
    timing = replace(FAST, metadata_refresh_interval=0.25)
    async with Simulator(port=0, interval=0.03, control_lab=True) as simulator:
        async with SpaRuntime(
            "127.0.0.1", simulator.port, mode=Mode.CLASSIC_RS485, timing=timing
        ) as runtime:
            await runtime.connection.wait_for(lambda _: runtime.metadata_complete, timeout=2)
            simulator.fault_payload = bytes((1, 0, 17, 0, 12, 0, 0, 76, 72, 72))
            await runtime.connection.wait_for(lambda _: runtime.state.fault.count == 1, timeout=2)
            assert runtime.state.fault.name == "flow_failed"
            assert simulator.stats.connections == 1
            assert simulator.physical_commands == 0
