"""Session actions are registered globally and validate the selected loaded entry."""

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from ._core.protocol.messages import TemperatureUnit
from ._core.session_time import deadline
from .const import DOMAIN
from .coordinator import SpaCoordinator
from .time import minute_of_day

ENTRY_SCHEMA: dict[Any, Any] = {vol.Required("config_entry_id"): cv.string}
START_SCHEMA = vol.Schema(
    {
        **ENTRY_SCHEMA,
        vol.Required("target_temperature"): vol.Coerce(float),
        vol.Required("maintenance_temperature"): vol.Coerce(float),
        vol.Optional("temperature_unit", default="C"): vol.In(("C", "F")),
        vol.Optional("duration"): cv.positive_time_period,
        vol.Optional("end_time"): cv.string,
    }
)
ADJUST_SCHEMA = vol.Schema(
    {
        **ENTRY_SCHEMA,
        vol.Optional("duration", default={"minutes": 30}): cv.positive_time_period,
    }
)
BATH_SCHEMA = vol.Schema(
    {
        **ENTRY_SCHEMA,
        vol.Optional("minimum_temperature_c", default=36.5): vol.Coerce(float),
        vol.Optional("duration"): cv.positive_time_period,
        vol.Optional("end_time"): cv.string,
    }
)
FILTER_SCHEMA = vol.Schema(
    {
        **ENTRY_SCHEMA,
        vol.Required("cycle"): vol.In((1, 2)),
        vol.Optional("start"): cv.time,
        vol.Optional("end"): cv.time,
        vol.Optional("enabled"): cv.boolean,
    }
)


@callback
def async_register_actions(hass: HomeAssistant) -> None:
    async def handle(call: ServiceCall) -> None:
        entry = hass.config_entries.async_get_entry(call.data["config_entry_id"])
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.state != ConfigEntryState.LOADED
            or not isinstance(entry.runtime_data, SpaCoordinator)
        ):
            raise ServiceValidationError("Select a loaded Balboa RS485 integration entry")
        controller = entry.runtime_data.sessions.runner
        try:
            if call.service == "set_filter_cycle":
                await entry.runtime_data.async_filter_change(
                    call.data["cycle"],
                    start=minute_of_day(call.data["start"]) if "start" in call.data else None,
                    end=minute_of_day(call.data["end"]) if "end" in call.data else None,
                    enabled=call.data.get("enabled"),
                )
            elif call.service in ("start_heating_session", "start_bathing_session"):
                duration = call.data.get("duration")
                end = deadline(
                    now=dt_util.utcnow(),
                    zone=dt_util.get_default_time_zone(),
                    duration=duration.total_seconds() if duration is not None else None,
                    end_time=call.data.get("end_time"),
                )
                if call.service == "start_bathing_session":
                    await controller.async_start_bathing(
                        end=end, minimum_c=call.data["minimum_temperature_c"]
                    )
                else:
                    await controller.async_start(
                        end=end,
                        target=call.data["target_temperature"],
                        maintenance=call.data["maintenance_temperature"],
                        unit=TemperatureUnit(call.data["temperature_unit"]),
                    )
            elif call.service in ("extend_heating_session", "reduce_heating_session"):
                seconds = call.data["duration"].total_seconds()
                if seconds <= 0:
                    raise ValueError("Adjustment duration must be positive")
                await controller.async_adjust(
                    seconds=seconds if call.service == "extend_heating_session" else -seconds
                )
            elif call.service == "abandon_heating_session":
                await controller.async_abandon()
            else:
                await controller.async_cancel()
        except (ValueError, HomeAssistantError) as err:
            raise ServiceValidationError(str(err)) from err
        finally:
            entry.runtime_data.async_set_updated_data(
                entry.runtime_data.runtime.connection.snapshot
            )

    hass.services.async_register(DOMAIN, "start_heating_session", handle, schema=START_SCHEMA)
    hass.services.async_register(DOMAIN, "set_filter_cycle", handle, schema=FILTER_SCHEMA)
    hass.services.async_register(DOMAIN, "start_bathing_session", handle, schema=BATH_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        "abandon_heating_session",
        handle,
        schema=vol.Schema(
            {**ENTRY_SCHEMA, vol.Required("confirm"): vol.All(cv.boolean, vol.Equal(True))}
        ),
    )
    hass.services.async_register(
        DOMAIN, "cancel_heating_session", handle, schema=vol.Schema(ENTRY_SCHEMA)
    )
    for name in ("extend_heating_session", "reduce_heating_session"):
        hass.services.async_register(DOMAIN, name, handle, schema=ADJUST_SCHEMA)
