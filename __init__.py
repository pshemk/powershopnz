"""PowerShop integration."""


from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN,
    CONF_ACCOUNT_ID,
    SENSORS_GROUPS_MAP,
)
from .coordinator import PowershopCoordinator

_LOGGER = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# A list of the different platforms we wish to setup.
# Add or remove from this list based on your specific need
# of entity platform types.
# ----------------------------------------------------------------------------
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
]

type PowershopConfigEntry = ConfigEntry[RuntimeData]


@datacla
class RuntimeData:
    """Class to hold your data."""

    coordinator: DataUpdateCoordinator
    # cancel_update_listener: Callable


async def async_setup_entry(hass: HomeAssistant, config_entry: PowershopConfigEntry) -> bool:


    _LOGGER.debug("async setup entry")

    enabled_groups = config_entry.options
    registry = er.async_get(hass)

    for entity in er.async_entries_for_config_entry(
        registry,
        config_entry.entry_id,
    ):
        group = _sensor_group_from_unique_id(
            entity.unique_id,
            config_entry.data[CONF_ACCOUNT_ID],
        )

        if group and enabled_groups.get(group) is False:
            _LOGGER.debug(f"removing entity: {entity.entity_id}")
            registry.async_remove(entity.entity_id)    
  
    coordinator = PowershopCoordinator(hass, config_entry)

    await coordinator.async_load_stores()
    
    # ----------------------------------------------------------------------------
    # Perform an initial data load from api.
    # async_config_entry_first_refresh() is special in that it does not log errors
    # if it fails.
    # ----------------------------------------------------------------------------
    # ----------------------------------------------------------------------------
    # Initialise a listener for config flow options changes.
    # This will be removed automatically if the integraiton is unloaded.
    # See config_flow for defining an options setting that shows up as configure
    # on the integration.
    # If you do not want any config flow options, no need to have listener.
    # ----------------------------------------------------------------------------

    # cancel_update_listener = config_entry.async_on_unload(
    #     config_entry.add_update_listener(_async_update_listener)
    # )

    await coordinator.async_config_entry_first_refresh()
        
    # ----------------------------------------------------------------------------
    # Test to see if api initialised correctly, else raise ConfigNotReady to make
    # HA retry setup.
    # Change this to match how your api will know if connected or successful
    # update.
    # ----------------------------------------------------------------------------
    # if not coordinator.data:
    #     raise ConfigEntryNotReady

    # ----------------------------------------------------------------------------
    # Add the coordinator and update listener to your config entry to make
    # accessible throughout your integration
    # ----------------------------------------------------------------------------
    config_entry.runtime_data = RuntimeData(coordinator)

    # ----------------------------------------------------------------------------
    # Setup platforms (based on the list of entity types in PLATFORMS defined above)
    # This calls the async_setup method in each of your entity type files.
    # ----------------------------------------------------------------------------

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    # ----------------------------------------------------------------------------
    # Setup global services
    # This can be done here but included in a seperate file for ease of reading.
    # See also light.py for entity services examples
    # ----------------------------------------------------------------------------
    # ExampleServicesSetup(hass, config_entry)

    # Return true to denote a successful setup.
    return True

def _sensor_group_from_unique_id( unique_id: str, account_id: str ) -> str | None:
    prefix = f"{DOMAIN}_{account_id}_"

    if not unique_id.startswith(prefix):
        return None

    sensor_key = unique_id.removeprefix(prefix)
    
    return next(
        (
            group
            for key, group in SENSORS_GROUPS_MAP.items()
            if  key in sensor_key 
        ),
        None,
    )      

# async def _async_update_listener(hass: HomeAssistant, config_entry: ConfigEntry):
#     """Handle config options update.

#     Reload the integration when the options change.
#     Called from our listener created above.
#     """

#     _LOGGER.debug(
#         "Config entry updated: options=%s",
#         config_entry.options,
#     )    

#     _LOGGER.debug("in async update listener")
#     enabled_groups = config_entry.options
#     registry = er.async_get(hass)

#     for entity in er.async_entries_for_config_entry(
#         registry,
#         config_entry.entry_id,
#     ):
#         group = _sensor_group_from_unique_id(
#             entity.unique_id,
#             config_entry.data[CONF_ACCOUNT_ID],
#         )

#         if group and enabled_groups.get(group) is False:
#             _LOGGER.debug(f"removing entity: {entity.entity_id}")
#             registry.async_remove(entity.entity_id)    

#     await hass.config_entries.async_reload(config_entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Delete device if selected from UI.

    Adding this function shows the delete device option in the UI.
    Remove this function if you do not want that option.
    You may need to do some checks here before allowing devices to be removed.
    """
    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: PowershopConfigEntry) -> bool:
    """Unload a config entry.

    This is called when you remove your integration or shutdown HA.
    If you have created any custom services, they need to be removed here too.
    """

    # Unload services
    for service in hass.services.async_services_for_domain(DOMAIN):
        hass.services.async_remove(DOMAIN, service)

    # Unload platforms and return result
    return await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)


