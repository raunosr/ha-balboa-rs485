"""Allowlisted diagnostics: never serialize arbitrary entry data or raw frames."""

from enum import Enum
from typing import Any

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant

from ._core.command.engine import Stage, Transaction
from ._core.protocol.settings import FilterSchedule
from ._core.state.model import Control, Value
from .coordinator import BalboaConfigEntry


def _value(value: Value | None) -> str | bool | int | float | list[dict[str, Any]] | None:
    if isinstance(value, FilterSchedule):
        return [
            {
                "start_hour": c.start_hour,
                "start_minute": c.start_minute,
                "duration_minutes": c.duration_minutes,
                "enabled": c.enabled,
            }
            for c in value.cycles
        ]
    return value.name.lower() if isinstance(value, Enum) else value


def _age(now: float, timestamp: float | None) -> float | None:
    return None if timestamp is None else round(max(0, now - timestamp), 3)


def _transaction(item: Transaction, now: float) -> dict[str, Any]:
    return {
        "intent_id": item.action.intent.id,
        "control": item.action.intent.control.value,
        "desired": _value(item.action.intent.desired),
        "requested_reminder_code": item.action.intent.reminder_code,
        "starting_value": _value(item.starting_value),
        "resulting_value": _value(item.resulting_value),
        "epoch": item.action.epoch,
        "message_type": f"BF{item.action.frame.message_type:02X}",
        "requested_age": _age(now, item.action.intent.requested_at),
        "cts_age": _age(now, item.cts_at),
        "sent_age": _age(now, item.sent_at),
        "result": item.result.value,
        "latency": item.latency,
        "reason": item.reason,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BalboaConfigEntry
) -> dict[str, Any]:
    runtime = entry.runtime_data.runtime
    snapshot = runtime.connection.snapshot
    now = hass.loop.time()
    information = snapshot.configuration.information if snapshot.configuration else None
    state = runtime.state
    fault = state.fault if state else None
    passive = snapshot.observed_status
    history = runtime.engine.history
    latencies = [
        item.latency
        for item in history
        if item.result == Stage.VERIFIED and item.latency is not None
    ]
    return {
        "connection": {
            "host": REDACTED,
            "port": REDACTED,
            "state": snapshot.state.value,
            "mode": snapshot.mode.value,
            "requested_mode": runtime.connection.requested_mode.value,
            "direct_unarbitrated": runtime.connection.requested_mode.direct,
            "candidate": snapshot.candidate.value,
            "available": snapshot.available,
            "epoch": snapshot.epoch,
            "channel": snapshot.channel,
            "channel_failure": snapshot.channel_failure,
            "channel_assignment": {
                "attempts": snapshot.assignment_requests,
                "limit": 3,
                "requested": snapshot.channel_assignment.requested,
                "responses": snapshot.channel_assignment.responses,
                "correlated": snapshot.channel_assignment.correlated,
                "reply_opportunities": snapshot.channel_assignment.reply_opportunities,
                "pending": snapshot.channel_assignment.pending,
                "ack_on_cts": snapshot.channel_assignment.ack_on_cts,
            },
            "last_rx_age": _age(now, snapshot.health.last_rx),
            "last_valid_frame_age": _age(now, snapshot.health.last_valid_frame),
            "last_status_age": _age(now, snapshot.health.last_status),
            "last_ready_age": _age(now, snapshot.health.last_ready),
            "status_stale": snapshot.health.status_stale,
            "ready_missing": snapshot.health.ready_missing,
            "frames_per_second": snapshot.health.frames_per_second,
            "ready_interval_mean": snapshot.health.ready_interval_mean,
            "ready_interval_max": snapshot.health.ready_interval_max,
            "rx_frames": snapshot.rx_frames,
            "tx_frames": snapshot.tx_frames,
            "crc_errors": snapshot.crc_errors,
            "discarded_bytes": snapshot.discarded_bytes,
            "invalid_messages": snapshot.invalid_messages,
            "recoveries": snapshot.recoveries,
            # Socket error strings can contain resolved IPs: do not include them.
            "error_present": snapshot.last_error is not None,
        },
        "device": {
            "model": information.model if information else None,
            "firmware": list(information.software_version) if information else None,
            "software_id": list(information.software_id) if information else None,
            "setup": information.setup if information else None,
            "configuration_signature": REDACTED if information else None,
            "configuration_revision": snapshot.configuration_revision,
            "metadata_complete": runtime.metadata_complete,
            "metadata_failures": list(runtime.metadata_failures),
        },
        "controls_enabled": entry.runtime_data.controls_enabled,
        "controls_safe": state.controls_safe if state else False,
        "controls_blocked_reason": state.controls_blocked_reason if state else "not_synchronized",
        "observations": {
            "passive_status": {
                "water_temperature": passive.current_temperature,
                "target_temperature": passive.target_temperature,
                "unit": passive.unit.value,
                "pumps_raw": list(passive.pumps_raw),
                "filter_flags": passive.frame.payload[9],
                "filter_running": list(
                    passive.filter_running_for_model(state.model if state else None)
                ),
                "clock": passive.clock,
                "priming": passive.priming,
                "hold": passive.hold,
                "operating_mode": passive.frame.payload[0],
                "initialization_mode": passive.frame.payload[1],
                "reminder_code": passive.reminder_code,
                "reminder": passive.reminder,
                "notification_flags": passive.frame.payload[18],
                "panel_locked": passive.panel_locked,
                "settings_locked": passive.settings_locked,
            }
            if passive
            else None,
            "supported_controls": [c.value for c in Control if state and state.options(c)],
            "circulation_pump_supported": state.has_circulation_pump if state else None,
            "filters": _value(FilterSchedule(state.filters.cycles))
            if state and state.filters
            else None,
            "filter_metadata_age": _age(now, state.filters_at) if state else None,
            "filter_running_consensus": list(state.status.filter_running_consensus)
            if state
            else None,
            "filter_running_interpretation": "bp6013g2_cycle2_observed_cycle1_source_inferred"
            if state and state.model == "BP6013G2"
            else "source_consensus_not_hardware_validated",
            "latest_historical_fault": {
                "count": fault.count,
                "code": fault.code if fault.count else None,
                "name": fault.name,
            }
            if fault
            else None,
        },
        "session": {
            "intent": entry.runtime_data.sessions.session.to_record()
            if entry.runtime_data.sessions.session
            else None,
            "blocked_reason": entry.runtime_data.sessions.runner.blocked_reason,
            "storage_failed": entry.runtime_data.sessions.runner.storage_failed,
        },
        "prediction": {
            **entry.runtime_data.prediction.attributes,
            "model_version": 1,
            "samples": entry.runtime_data.prediction.model.samples,
            "coefficients": list(entry.runtime_data.prediction.model.coefficients),
            "mae_minutes": entry.runtime_data.prediction.model.mae,
            "fallback_c_per_hour": entry.runtime_data.prediction.model.fallback,
            "outdoor_configured": entry.runtime_data.prediction.outdoor_entity is not None,
        },
        "commands": {
            "window_count": len(history),
            "verified": sum(item.result == Stage.VERIFIED for item in history),
            "failed": sum(item.result == Stage.FAILED for item in history),
            "cancelled": sum(item.result == Stage.CANCELLED for item in history),
            "mean_verification_latency": sum(latencies) / len(latencies) if latencies else None,
            "history": [_transaction(item, now) for item in history],
        },
    }
