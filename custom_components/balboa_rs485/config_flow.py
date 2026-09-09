"""User configuration; no hardware traffic merely for opening the form."""

from typing import Any, Self

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import selector

from ._core.transport.connection import SpaConnection
from ._core.transport.policy import Mode
from .const import CONF_CONTROLS, CONF_DIRECT_RISK, CONF_FALLBACK, CONF_MODE, CONF_OUTDOOR, DOMAIN

CONNECTION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=8899): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        # Keep the loopback-only experiment out of HA, even after explicit promotion.
        vol.Required(CONF_MODE, default=Mode.AUTO.value): vol.In(
            [mode.value for mode in Mode if mode != Mode.DIRECT_RS485_TCP_LAB]
        ),
        vol.Optional(CONF_DIRECT_RISK, default=False): bool,
    }
)


class BalboaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure a single local Elfin/BWA endpoint."""

    VERSION = 1
    _endpoint: tuple[str, int] | None = None

    def is_matching(self, other_flow: Self) -> bool:
        return self._endpoint is not None and self._endpoint == other_flow._endpoint

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BalboaOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._connection_step("user", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._connection_step("reconfigure", user_input, self._get_reconfigure_entry())

    async def _connection_step(
        self, step: str, user_input: dict[str, Any] | None, entry: ConfigEntry | None = None
    ) -> ConfigFlowResult:
        errors = {}
        if (
            user_input is not None
            and user_input.get(CONF_MODE) == Mode.DIRECT_RS485_TCP.value
            and user_input.get(CONF_DIRECT_RISK) is not True
        ):
            errors[CONF_DIRECT_RISK] = "direct_risk_required"
        elif user_input is not None:
            data = {**user_input, CONF_HOST: user_input[CONF_HOST].strip().lower()}
            if data[CONF_MODE] != Mode.DIRECT_RS485_TCP.value:
                # Do not add a default key to legacy entries: a no-op save would
                # otherwise reconnect and reset the finite allocation budget.
                data.pop(CONF_DIRECT_RISK, None)
                if entry is not None and CONF_DIRECT_RISK in entry.data:
                    data[CONF_DIRECT_RISK] = False
            self._async_abort_entries_match(
                {CONF_HOST: data[CONF_HOST], CONF_PORT: data[CONF_PORT]}
            )
            self._endpoint = (data[CONF_HOST], data[CONF_PORT])
            if self.hass.config_entries.flow.async_has_matching_flow(self):
                return self.async_abort(reason="already_in_progress")
            try:
                await self._validate_connection(data, entry)
            except (TimeoutError, OSError, ValueError):
                self._endpoint = None
                errors["base"] = "cannot_connect"
            else:
                if entry is not None:
                    changed = self.hass.config_entries.async_update_entry(
                        entry, data={**entry.data, **data}
                    )
                    # Loaded entries use their update listener; unloaded entries have none.
                    if changed and not entry.update_listeners:
                        self.hass.config_entries.async_schedule_reload(entry.entry_id)
                    return self.async_abort(reason="reconfigure_successful")
                return self.async_create_entry(title="Balboa Spa", data=data)
        return self.async_show_form(
            step_id=step,
            data_schema=self.add_suggested_values_to_schema(
                CONNECTION_SCHEMA, user_input or (entry.data if entry else {})
            ),
            errors=errors,
        )

    async def _validate_connection(self, data: dict[str, Any], entry: ConfigEntry | None) -> None:
        if (
            entry is not None
            and hasattr(entry, "runtime_data")
            and all(entry.data[key] == data[key] for key in (CONF_HOST, CONF_PORT))
            and entry.runtime_data.runtime.connection.running
        ):
            # Do not open a competing validation socket to an already owned endpoint.
            snapshot = entry.runtime_data.runtime.connection.snapshot
            if snapshot.status is None or snapshot.health.status_stale:
                raise TimeoutError("The existing connection has no fresh status")
            return
        # Validation must not negotiate a channel or transmit configuration queries.
        async with SpaConnection(data[CONF_HOST], data[CONF_PORT]) as connection:
            await connection.wait_for(lambda snapshot: snapshot.status is not None)


class BalboaOptionsFlow(OptionsFlow):
    """Change preferences without reconnecting or allocating another RS485 channel."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            retained = {
                key: value
                for key, value in self.config_entry.options.items()
                if key not in (CONF_CONTROLS, CONF_OUTDOOR, CONF_FALLBACK)
            }
            return self.async_create_entry(data={**retained, **user_input})
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CONTROLS, default=self.config_entry.options.get(CONF_CONTROLS, False)
                    ): bool,
                    vol.Optional(
                        CONF_OUTDOOR,
                        description={
                            "suggested_value": self.config_entry.options.get(CONF_OUTDOOR)
                        },
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                    ),
                    vol.Required(
                        CONF_FALLBACK, default=self.config_entry.options.get(CONF_FALLBACK, 2.0)
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=8)),
                }
            ),
        )
