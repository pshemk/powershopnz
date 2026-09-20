"""Powershop NZ sensors."""

from __future__ import annotations

from datetime import timedelta, datetime, timezone
from zoneinfo import ZoneInfo

from typing import Any, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_SCAN_INTERVAL,
    UnitOfEnergy,
)

import statistics
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant_historical_sensor import (  # PollUpdateMixin,
    HistoricalSensor,
    HistoricalState,
    group_by_interval,
)

from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
)

from homeassistant.components.recorder.statistics import StatisticsRow

from homeassistant.const import (
    CURRENCY_DOLLAR,
    UnitOfEnergy,
)

from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.typing import ConfigType
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import (
    CONF_ACCOUNTS,
    CONF_REFRESH_TOKEN,
    CONF_ACCOUNT_ID,
    CONF_PROPERTY_ID,
    CONF_PROPERTY_ADDRESS,
    DOMAIN,
    SENSORS_GROUPS_MAP
)
from .coordinator import PowershopCoordinator

type PowershopConfigEntry = ConfigEntry[RuntimeData]

import logging
_LOGGER = logging.getLogger(__name__)



SENSORS_GENERIC = [

    SensorEntityDescription(
        key='billing_period_usage_total',
        name='Billing period usage: Total',
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        icon="mdi:home-lightning-bolt-outline",
    ),
    SensorEntityDescription(
        key='nominal_unit_cost',
        name='Nominal rate',
        native_unit_of_measurement='$/kWh',
        device_class='none',
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=4,
        icon="mdi:cash",                
    ),
    SensorEntityDescription(
        key='effective_unit_cost',
        name='Effective rate',
        native_unit_of_measurement='$/kWh',
        device_class='none',
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=4,
        icon="mdi:cash",        
    ),
    SensorEntityDescription(
        key="daily_charge",
        name="Daily charge",
        native_unit_of_measurement=CURRENCY_DOLLAR,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:cash",        
        suggested_display_precision=4,
    ),
    SensorEntityDescription(
        key='unit_rate_type',
        name='Current rate type',
        icon="mdi:store-clock-outline",
    ),
    SensorEntityDescription(
        key='billing_period_cost_total_nominal',
        name='Billing period cost: Nominal Total',
        native_unit_of_measurement=CURRENCY_DOLLAR,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:cash",        
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key='billing_period_cost_total_effective',
        name='Billing period cost: Effective Total',
        native_unit_of_measurement=CURRENCY_DOLLAR,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:cash",        
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key='effective_cost_ratio',
        name='Effective cost ratio',
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=4,
        icon="mdi:gauge",
    ),
    SensorEntityDescription(
        key='powerpacks_available_balance',
        name='Powerpacks - available balance',
        native_unit_of_measurement=CURRENCY_DOLLAR,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:wallet",        
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key='powerpacks_future_balance',
        name='Powerpacks - future balance',
        native_unit_of_measurement=CURRENCY_DOLLAR,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:wallet-plus",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key='next_billing_date',
        name='Next billing date',
        device_class=SensorDeviceClass.DATE,
    ),
    SensorEntityDescription(
        key='current_billing_period_start_date',
        name='Current billing period start date',
        device_class=SensorDeviceClass.DATE,
    ),
    SensorEntityDescription(
        key='current_billing_period_end_date',
        name='Current billing period end date',
        device_class=SensorDeviceClass.DATE,
    ),
    SensorEntityDescription(
        key='billing_period_usage_daily_charge',
        name='Billing period days so far',
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=0,
        icon="mdi:calendar-month",
    ),
]

SENSORS_PER_RATE = [
    SensorEntityDescription(
        key="nominal_unit_cost",
        name="Nominal rate: ",
        native_unit_of_measurement='$/kWh',
        device_class='none',
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=4,
        icon="mdi:cash",        
    ),
    SensorEntityDescription(
        key="effective_unit_cost",
        name="Effective rate: ",
        native_unit_of_measurement='$/kWh',
        device_class='none',
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=4,
        icon="mdi:cash",        
    ),
    SensorEntityDescription(
        key='billing_period_usage',
        name='Billing period usage: ',
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        icon="mdi:home-lightning-bolt-outline",        
    ),
]

SENSORS_HISTORICAL = [

    SensorEntityDescription(
        key='historical_usage_total',
        name='Power usage',
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:chart-bar",
    ),
    SensorEntityDescription(
        key='historical_cost_total',
        name='Power cost',
        native_unit_of_measurement=CURRENCY_DOLLAR,
        # device_class=SensorDeviceClass.MEASUREMENT,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:chart-bar",
        suggested_display_precision=2,
    ),    
]

SENSORS_HISTORICAL_PER_RATE = [

    SensorEntityDescription(
        key='historical_usage',
        name='Power usage',
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:chart-bar-stacked",        
    ),
    SensorEntityDescription(
        key='historical_cost',
        name='Power cost',
        native_unit_of_measurement=CURRENCY_DOLLAR,
        # device_class=SensorDeviceClass.MEASUREMENT,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:chart-bar-stacked",
        suggested_display_precision=2,
    ),        
]


def _sensor_to_group(sensor: str) -> str | None:
    return next(
        (
            sensor_group
            for sensor_key, sensor_group in SENSORS_GROUPS_MAP.items()
            if sensor_key in sensor 
        ),
        None,
    )

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: PowershopConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up the Sensors."""
    coordinator: PowershopCoordinator = config_entry.runtime_data.coordinator

    _LOGGER.debug("in sensor async_setup_entry")
    #get list of rates to turn into sensors
    rate_types = await coordinator.get_rate_types()

    #Create rate-related sensors, they vary between regions and lines companies
    async_add_entities(
        PowershopSensor(coordinator, 
        SensorEntityDescription(
            key=f"{sensor.key}_{rate_name}",
            name=f"{sensor.name} {rate_type["name"]}",
            native_unit_of_measurement=sensor.native_unit_of_measurement,
            device_class=sensor.device_class,
            state_class=sensor.state_class,
            icon=sensor.icon,
            suggested_display_precision=sensor.suggested_display_precision,
        ),
        config_entry)
        for sensor in SENSORS_PER_RATE if config_entry.options.get(_sensor_to_group(sensor.key)) == True
        for rate_name, rate_type in rate_types.items()
    )

    #Regular sensors
    async_add_entities(
        PowershopSensor(coordinator, sensor, config_entry)
        for sensor in SENSORS_GENERIC if config_entry.options.get(_sensor_to_group(sensor.key)) == True
    )
    #Historical sensors - no current state
    async_add_entities(
        PowershopHistoricalSensor(coordinator, sensor, config_entry)
        for sensor in SENSORS_HISTORICAL if config_entry.options.get(_sensor_to_group(sensor.key)) == True
    )

    #Historical sensor per rate
    async_add_entities(
        PowershopHistoricalSensor(coordinator, 
        SensorEntityDescription(
            key=f"{sensor.key}_{rate_name}",
            name=f"{sensor.name} {rate_type["name"]}",
            native_unit_of_measurement=sensor.native_unit_of_measurement,
            device_class=sensor.device_class,
            state_class=sensor.state_class,
            icon=sensor.icon,
            suggested_display_precision=sensor.suggested_display_precision,
        ),
        config_entry)
        for sensor in SENSORS_HISTORICAL_PER_RATE if config_entry.options.get(_sensor_to_group(sensor.key)) == True
        for rate_name, rate_type in rate_types.items()
    )


class PowershopSensor(CoordinatorEntity[PowershopCoordinator], SensorEntity):
    """A sensor that reads from the Powershop coordinator."""

    def __init__(
        self,
        coordinator: PowershopCoordinator,
        description: SensorEntityDescription,
        config_entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        _LOGGER.debug(f"powershop sensor init: {description.name}")
        
        self.entity_description = description
        self.coordinator = coordinator
        
        property_id = config_entry.data.get(CONF_PROPERTY_ID, "unknown")
        property_address = config_entry.data.get(CONF_PROPERTY_ADDRESS, "unknown")
        
        self._attr_unique_id = f"{DOMAIN}_{property_id}_{description.key}"
        self._attr_name = f"{description.name}"
        self.entity_id = f"sensor.{DOMAIN}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, property_id)},
            "name": f"{property_address}",
            "manufacturer": "Powershop NZ",
            "model": "Account",
        }
        self._key = description.key

    @property
    def native_value(self) -> Any:
        if not self.coordinator.data:
            return None

        # _LOGGER.debug(f"returning data: for {self._key}: " + str(self.coordinator.data.get(self._key)))
        return self.coordinator.data.get(self._key)

class PowershopHistoricalSensor(CoordinatorEntity[PowershopCoordinator], HistoricalSensor,SensorEntity):
    """A sensor that reads historical data from the coordinator"""

    def __init__(
        self,
        coordinator: PowershopCoordinator,
        description: SensorEntityDescription,
        config_entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        _LOGGER.debug(f"powershop historical sensor init: {description.name}")

        property_id = config_entry.data.get(CONF_PROPERTY_ID, "unknown")
        property_address = config_entry.data.get(CONF_PROPERTY_ADDRESS, "unknown")

        self._attr_unique_id = f"{DOMAIN}_{property_id}_{description.key}"
        self._attr_name = f"{description.name}"
        self.entity_id = f"sensor.{DOMAIN}_{description.key}"
        self._attr_icon=description.icon
        self._attr_device_info = {
            "identifiers": {(DOMAIN, property_id)},
            "name": f"{property_address}",
            "manufacturer": "Powershop NZ",
            "model": "Account",
        }
        self._key = description.key
        self._native_unit_of_measurement=description.native_unit_of_measurement
        self._device_class=description.device_class
        self._state_class=description.state_class


        self._attr_state = None

    @property
    @override
    def historical_states(self) -> list[HistoricalState]:
        """Return the historical state of the sensor."""
        return self._attr_historical_states

    async def async_update_historical(self):
        
        historical_data = await self.coordinator.get_historical_data(self._key)

        
        historical_states = [
            HistoricalState(
                state=value,
                timestamp=ts,
            )
            for ts, value in historical_data.items()
        ]

        self._attr_historical_states = historical_states
        # _LOGGER.debug("historical data updated from upstream")

    def get_statistic_metadata(self) -> StatisticMetaData:
        meta = super().get_statistic_metadata()
        meta["has_sum"] = True
        meta["unit_of_measurement"] = self._native_unit_of_measurement 
        meta["unit_class"] = self._device_class
        return meta

    async def async_calculate_statistic_data(
        self, hist_states: list[HistoricalState], *, latest: dict | None = None
    ) -> list[StatisticData]:

        accumulated = latest["sum"] if latest else 0

        ret = []
        for block_ts, collection_it in group_by_interval(
            hist_states, granularity=60 * 60
        ):
            collection = list(collection_it)

            partial_sum = sum([x.state for x in collection])
            accumulated = accumulated + partial_sum

            dt = datetime.fromtimestamp(block_ts).replace(tzinfo=ZoneInfo("UTC"))

            ret.append(
                StatisticData(
                    start=dt,
                    state=partial_sum,
                    sum=accumulated,
                )
            )
        return ret
