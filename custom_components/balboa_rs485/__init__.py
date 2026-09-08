"""Native Home Assistant adapter for the independent Balboa RS485 runtime."""

from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .coordinator import BalboaConfigEntry, SpaCoordinator
from .prediction import model_store
from .services import async_register_actions
from .sessions import session_store

PLATFORMS = [
    Platform.CLIMATE,
    Platform.FAN,
    Platform.LIGHT,
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.BUTTON,
    Platform.TIME,
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_register_actions(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BalboaConfigEntry) -> bool:
    coordinator = entry.runtime_data = SpaCoordinator(hass, entry)
    try:
        await coordinator.async_open()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await coordinator.async_close()
        raise

    async def stop(_: Event) -> None:
        await coordinator.async_close()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop))
    entry.async_on_unload(entry.add_update_listener(async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BalboaConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.async_close()
    return True


async def async_remove_entry(hass: HomeAssistant, entry: BalboaConfigEntry) -> None:
    """Deletion is explicit; ordinary unload/restart must retain session intent."""
    await session_store(hass, entry.entry_id).async_remove()
    await model_store(hass, entry.entry_id).async_remove()


async def async_options_updated(hass: HomeAssistant, entry: BalboaConfigEntry) -> None:
    if entry.data != entry.runtime_data.connection_data:
        await hass.config_entries.async_reload(entry.entry_id)
        return
    entry.runtime_data.async_options_updated()
