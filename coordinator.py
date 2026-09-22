"""Powershop NZ data coordinator."""

from __future__ import annotations

from datetime import date, time, timedelta, datetime
import logging
import asyncio
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.start import async_at_started

from homeassistant.util import dt as dt_util

from homeassistant.const import (
    CONF_SCAN_INTERVAL,
)

from .api import PowershopApiClient
from .store import PowershopStore

from .const import (
    DOMAIN,
    CONF_ACCOUNT_ID,
    CONF_PROPERTY_ID,
    CONF_PROPERTY_ADDRESS,
    CONF_REFRESH_TOKEN,
    CONF_REPROCESS_DATA,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_API_CALL_INTERVAL,
)

type PowershopConfigEntry = ConfigEntry[RuntimeData]

_LOGGER = logging.getLogger(__name__)

STORE_NAMES = (
    "rates_schedule",
    "rates",
    "powerpacks",
    "powerpacks_balances",
    "state",
    "usage",
    "billing_dates",
    "sensors",
    "sensors_pointers"
)

class PowershopCoordinator(
    DataUpdateCoordinator[dict[str, Any]]
):
    """Coordinator for one Powershop account."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: PowershopConfigEntry
    ) -> None:
        """Initialize the coordinator."""

        self.refresh_token = config_entry.data[CONF_REFRESH_TOKEN]
        self._account_id = config_entry.data[CONF_ACCOUNT_ID]
        self._property_id = config_entry.data[CONF_PROPERTY_ID]
        self._property_address = config_entry.data[CONF_PROPERTY_ADDRESS]
        self._config_entry = config_entry
        self._poll_interval = config_entry.options.get(CONF_SCAN_INTERVAL, timedelta(seconds=DEFAULT_UPDATE_INTERVAL))
        self._last_api_call = None
        self._process_usage_data = True  #force initial reprocessing

        self._stores = {
            name: PowershopStore(hass, f"{self._property_id}_{name}")
            for name in STORE_NAMES
        }

        self.hass = hass

        _LOGGER.debug("coordinator init")
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {self._property_id}",
            update_interval=self._poll_interval
        )

        self._usage_fetch_task: asyncio.Task | None = None
        self._usage_process_task: asyncio.Task | None = None

        self._cancel_usage_fetch_schedule = None
        self._cancel_usage_process_schedule = None

        self._api_client = PowershopApiClient(
            self.refresh_token,
            session=async_get_clientsession(hass),
        )

    async def _async_setup(self) -> None:
        """Schedule background usage fetching and processing."""

        #schedule periodic fetching of the usage data
        self._cancel_usage_fetch_schedule = async_track_time_interval(
            self.hass,
            self._schedule_usage_fetch,
            timedelta(minutes=10),
            # timedelta(hours=1),            
        )
        #run first fetch here, once HA is up
        async_at_started(
            self.hass,
            self._schedule_usage_fetch,
        )        

        #schedule periodic processing  of the usage data 
        self._cancel_usage_process_schedule = async_track_time_interval(
            self.hass,
            self._schedule_usage_process,
            timedelta(seconds=30),
        )

        #run first process here, once HA is up
        async_at_started(
            self.hass,
            self._schedule_usage_process,
        )        

        if self._config_entry.options.get(CONF_REPROCESS_DATA):
            _LOGGER.debug("Will force-reprocess current billing period")
            await self._stores["state"].async_save({
                **self._stores["state"].data,
                "last_usage_date": None
            })
            self.hass.config_entries.async_update_entry(
                self._config_entry,
                options={
                    **self._config_entry.options,
                    CONF_REPROCESS_DATA: False,
                },
            )            
            _LOGGER.debug(f"post processed: {self._config_entry.options}")


    async def _schedule_usage_fetch(self, *args) -> None:
        """Start a usage-fetch task when none is already running."""

        if  self._usage_fetch_task is not None and not self._usage_fetch_task.done():
            _LOGGER.debug("Usage fetch is already running")
            return

        self._usage_fetch_task = self.hass.async_create_task(
            self._async_update_usage()
        )

    async def _schedule_usage_process(self, *args) -> None:
        """Start a usage-processing task when none is already running."""

        if  self._usage_process_task is not None and not self._usage_process_task.done():
            _LOGGER.debug("Usage process is  already running")
            return

        self._usage_process_task = self.hass.async_create_task(
            self._async_process_usage()
        )

    async def async_shutdown(self) -> None:
        """Cancel background work, remove schedules, and close the API client."""

        if self._cancel_usage_fetch_schedule:
            self._cancel_usage_fetch_schedule()
            self._cancel_usage_fetch_schedule = None
        if self._cancel_usage_process_schedule:
            self._cancel_usage_process_schedule()
            self._cancel_usage_process_schedule = None

        tasks = [
            task
            for task in (self._usage_fetch_task, self._usage_process_task)
            if task is not None and not task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self._usage_fetch_task = None
        self._usage_process_task = None
        await self._api_client.disconnect()

    async def async_load_stores(self) -> None:
        """Load all persistent stores."""

        await asyncio.gather(
            *(store.async_load() for store in self._stores.values())
        )

    def _str_to_timestamp(self, data: dict[str, str]) -> dict[str, datetime]:
        """Convert stored ISO timestamp strings into datetime objects."""

        return {
            k: datetime.fromisoformat(v)
            for k, v in data.items() if isinstance(v, str)
        }

    async def _async_update_data(
        self,
    ) -> dict[str, Any]:
        """Getting data to feed the sensors."""

        try:
            refresh_powerpacks = False
            refresh_rates = False


            now = dt_util.now()
            today = now.strftime("%Y-%m-%d")
            month = now.strftime("%m")

            if not self._last_api_call or self._last_api_call + timedelta(seconds=DEFAULT_API_CALL_INTERVAL) < now:
                
                _LOGGER.debug("Calling the API")
                
                #get powerpack balances, if they changed - get powerpacks as well
                powerpacks_balances = await self._api_client.get_powerpacks_balances(
                    self._account_id
                )
                # _LOGGER.debug(
                #     "Powerpack balance: current=%s stored=%s",
                #     powerpacks_balances["powerpacks_available_balance"],
                #     self._stores["powerpacks_balances"].data.get(
                #         "powerpacks_available_balance"
                #     ),
                # )
                if powerpacks_balances["powerpacks_available_balance"] != self._stores["powerpacks_balances"].data.get("powerpacks_available_balance"):
                    _LOGGER.debug("powerpacks balance has changed, refreshing powerpacks")
                    refresh_powerpacks = True

                #store the current balances
                await self._stores["powerpacks_balances"].async_save(powerpacks_balances)

                #if this is a new day - fetch the rates (and schedules just to be safe) as well
                if self._stores["state"].data.get("last_rates_refresh") != today:
                    refresh_rates = True

                if not self._stores["powerpacks"].data  or refresh_powerpacks:
                    #get all powerpacks
                    _LOGGER.debug("Updating powerpacks")
                    powerpacks = await self._api_client.get_powerpacks(self._account_id)
                    powerpacks.sort(key=lambda x: x['ratio'], reverse=False)
                    await self._stores["powerpacks"].async_save(powerpacks)

                    #force reprocessing of the billing data
                    self._process_usage_data = True
                
                if refresh_rates:
                    #get rates and rates schedules/timeslots
                    _LOGGER.debug("Updating rates")
                    rates = await self._api_client.get_rates(self._account_id, self._property_id)
                    await self._stores["rates"].async_save({
                        **self._stores["rates"].data,
                        month: rates
                    })
                    
                    rates_schedule = await self._api_client.get_rates_schedule(
                        self._account_id, self._property_id
                    )
                    await self._stores["rates_schedule"].async_save(rates_schedule)

                    #get billing dates
                    _LOGGER.debug("Updating billing dates")
                    billing_dates = await self._api_client.get_billing_dates(self._account_id)
                    await self._stores["billing_dates"].async_save(billing_dates)

                    await self._stores["state"].async_save({
                        **self._stores["state"].data,
                        "last_rates_refresh": today
                    })

                    
                # Store refresh_token if needed
                if self._api_client.refresh_token != self._config_entry.data.get(CONF_REFRESH_TOKEN):
                    _LOGGER.debug("Updating refresh token")
                    self.hass.config_entries.async_update_entry(
                        self._config_entry,
                        data={
                            **self._config_entry.data,
                            CONF_REFRESH_TOKEN: self._api_client.refresh_token,
                        },
                    )
                
                #store call time
                self._last_api_call = now
            

            #identify the current rate from the rate schedule and return it
            timeslot = self._stores["rates_schedule"].data[now.weekday()][now.hour * 2 + now.minute // 30]
            current_rate = self._stores["rates"].data.get(month).get(timeslot).get("rate")
            effective_current_rate = current_rate * self._stores["sensors"].data.get("regular", {}).get("effective_cost_ratio", 1)

            return { 
                **{
                    f"nominal_unit_cost_{rate}": rate_details["rate"] for rate, rate_details in self._stores["rates"].data.get(month).items() if rate_details["type"] == "CONSUMPTION_CHARGE"
                }, 
                "daily_charge": self._stores["rates"].data.get(month).get("daily_charge").get("rate"),
                **self._stores["powerpacks_balances"].data,
                **self._str_to_timestamp(self._stores["billing_dates"].data.get("datetime")),
                "nominal_unit_cost": current_rate,
                "unit_rate_type": timeslot.replace("_", " ").title(),
                "effective_unit_cost": effective_current_rate,
                **self._stores["sensors"].data.get("regular", {})
            }
        except Exception:
            _LOGGER.exception(
                "Powershop coordinator UPDATE FAILED: %s",
                self._account_id,
            )
            raise

    async def _async_update_usage(self) -> None:
        """Synchronise usage data in the background."""

        try:
            _LOGGER.debug("Starting usage synchronisation")

            #just for now, reload the stores in case they got modified manually
            await self.async_load_stores()            

            #check available historic data
            if not self._stores["state"].data.get("last_usage_date"):
                #no historic data has been retrived yet
                _LOGGER.debug("Fetching all usage data; this might take a while")
                usage = await self._api_client.get_usage(self._account_id, self._property_id)
                await self._stores["usage"].async_save(usage["usage"])
                await self._stores["state"].async_save({
                    **self._stores["state"].data,
                    "last_usage_date": usage["last_usage_date"]
                })
                self._process_usage_data = True
            else:
                #only fetch new data
                last_usage_date = self._stores["state"].data.get("last_usage_date")
                _LOGGER.debug("Fetching usage data after %s", last_usage_date)
                usage = await self._api_client.get_usage(
                    self._account_id, self._property_id, last_usage_date
                )
                if usage["usage"]:
                    await self._stores["usage"].async_save({
                        **self._stores["usage"].data,
                        **usage["usage"],
                        })

                    #check if we actually got any new data
                    if usage["last_usage_date"] != self._stores["state"].data.get("last_usage_date"):
                        self._process_usage_data = True

                    await self._stores["state"].async_save({
                        **self._stores["state"].data,
                        "last_usage_date": usage["last_usage_date"]
                    })
            _LOGGER.debug("Usage synchronised")

        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Unable to synchronise usage data")
            raise


    async def _async_process_usage(self) -> None:
        """Process usage data in the background."""

        try:
            # _LOGGER.debug("Starting usage processing")

            #check if anything needs to processed:
            if self._process_usage_data:
                _LOGGER.debug("Data to process")
                _LOGGER.debug(
                    "Latest usage: %s, processed up to: %s",
                    self._stores["state"].data.get("last_usage_date"),
                    self._stores["state"].data.get("last_processed_date"),
                )

                #Determine the start and end of the current billing period                
                billing_period_start = self._stores["billing_dates"].data.get("datetime", {}).get("current_billing_period_start_date", "2100-01-01T00:00:00+00:00") 
                billing_period_end = self._stores["billing_dates"].data.get("datetime", {}).get("current_billing_period_end_date", "1970-01-01T00:00:00+00:00") 


                #the store class doesn't handle timestamps - depending where they come from they might be timestamps, ints/floats or strings
                #convert here
                if isinstance(billing_period_start, datetime):
                    pass
                elif isinstance(billing_period_start, (str)):
                    billing_period_start = datetime.fromisoformat(billing_period_start)
                elif isinstance(billing_period_start, (int, float)):
                    billing_period_start = datetime.fromtimestamp(billing_period_start, dt_util.get_time_zone("Pacific/Auckland"))
                else:
                    _LOGGER.debug("Billing start date type: %s", type(billing_period_start))
                    billing_period_start = datetime.fromtimestamp(0, dt_util.get_time_zone("Pacific/Auckland"))
                
                if isinstance(billing_period_end, datetime):
                    pass
                elif isinstance(billing_period_end, (str)):
                    billing_period_end = datetime.fromisoformat(billing_period_end)
                elif isinstance(billing_period_end, (int, float)):
                    billing_period_end = datetime.fromtimestamp(billing_period_end, dt_util.get_time_zone("Pacific/Auckland"))
                else:
                    _LOGGER.debug("Billing end date type: %s", type(billing_period_end))
                    billing_period_end = datetime.fromtimestamp(
                        0, dt_util.get_time_zone("Pacific/Auckland")
                    )

                _LOGGER.debug(f"billing period start: {billing_period_start.isoformat()} billing period end: {billing_period_end.isoformat()}")                
                #make sure we have the start and end dates in the right order
                if billing_period_start < billing_period_end:
                    billing_period_month = billing_period_start.strftime("%m")
                    billing_period_usage = 0
                    billing_period_cost = 0
                    billing_period_usage_by_rate = {
                        rate: 0
                        for rate in self._stores["rates"].data.get(
                            billing_period_month, {}
                        ).keys()
                    }
                    billing_period_usage_by_rate.setdefault("daily_charge", 0)

                    #Usage - stores per 1h consumption, the timeslot is the 30min in the middle of the hour
                    #we fetch 30mins intervals, so two have to be summed up
                    #also calulcate the sum for current billing period
                    usage_sensor_total = {}

                    usage_sensor_by_rate = {
                        rate: {}
                        for rate in self._stores["rates"].data.get(
                            billing_period_month, {}
                        ).keys()
                        if rate != "daily_charge"
                    }

                    last_seen_date = None
                    for ts, value in self._stores["usage"].data.items():
                        timestamp = datetime.fromisoformat(ts)
                        hour_timestamp = timestamp.replace(
                            minute=30, second=0, microsecond=0
                        )
                        hour_ts = hour_timestamp.isoformat()
                        usage_sensor_total[hour_ts] = usage_sensor_total.get(hour_ts, 0) + value
                        timeslot = self._stores["rates_schedule"].data[
                            timestamp.weekday()
                        ][timestamp.hour * 2 + timestamp.minute // 30]
                        usage_by_rate = usage_sensor_by_rate.setdefault(timeslot, {})
                        usage_by_rate[hour_ts] = usage_by_rate.get(hour_ts, 0) + value

                        if billing_period_start <= hour_timestamp < billing_period_end:
                            billing_period_usage += value
                            billing_period_usage_by_rate[timeslot] = (
                                billing_period_usage_by_rate.get(timeslot, 0) + value
                            )
                            if timestamp.date() != last_seen_date:
                                last_seen_date = timestamp.date()
                                billing_period_usage_by_rate["daily_charge"] += 1


                    #Cost - each 30mins segment must be costed indepedently and than the hour must be summed up
                    #also calulcate the sum for current billing period
                    cost_sensor_total = {}

                    cost_sensor_by_rate = {
                        rate: {}
                        for rate in self._stores["rates"].data.get(
                            billing_period_month, {}
                        ).keys()
                        if rate != "daily_charge"
                    }

                    for ts, value in self._stores["usage"].data.items():
                        timestamp = datetime.fromisoformat(ts)
                        hour_timestamp = timestamp.replace(
                            minute=30, second=0, microsecond=0
                        )
                        hour_ts = hour_timestamp.isoformat()

                        #determine timeslot (assume no schedule changes)
                        record_month = timestamp.strftime("%m")
                        timeslot = self._stores["rates_schedule"].data[
                            timestamp.weekday()
                        ][timestamp.hour * 2 + timestamp.minute // 30]
                        unit_cost = self._stores["rates"].data.get(record_month, {}).get(timeslot, {}).get("rate")
                        if unit_cost:
                            daily_charge = self._stores["rates"].data.get(record_month, {}).get("daily_charge", {}).get("rate", 0)
                            cost_sensor_total[hour_ts] = cost_sensor_total.get(hour_ts, 0) + unit_cost * value + daily_charge / 48

                            cost_by_rate = cost_sensor_by_rate.setdefault(timeslot, {})
                            cost_by_rate[hour_ts] = (
                                cost_by_rate.get(hour_ts, 0)
                                + unit_cost * value
                                + daily_charge / 48
                            )

                            if billing_period_start <= hour_timestamp < billing_period_end:
                                billing_period_cost += unit_cost * value + daily_charge / 48

                    #Determine effective costs, by using the purchased powerpacks
                    powerpacks = list.copy(self._stores["powerpacks"].data)

                    amount_paid = 0
                    total_cost = billing_period_cost
                    while total_cost > 0 and len(powerpacks) > 0:
                        powerpack = powerpacks.pop(0)
                        if datetime.strptime(powerpack["availableFrom"], "%Y-%m-%d")  > datetime.now():
                            continue
                        if powerpack['balance'] <= 0:
                            continue
                        offset = min(powerpack['balance'], total_cost)
                        _LOGGER.debug(
                            "Using %s to offset $%.2f of the cost, ratio: %.2f",
                            powerpack["name"],
                            offset,
                            powerpack["ratio"],
                        )
                        total_cost -= offset
                        amount_paid += offset * powerpack["ratio"]
                    
                    _LOGGER.debug("Total paid for powerpacks: $%.2f", amount_paid)
                    
                    if total_cost > 0:
                        amount_paid += total_cost
                    
                    total_consumption_cost = 0
                    billing_rates = self._stores["rates"].data.get(billing_period_month, {})
                    for rate in billing_rates:
                        if rate != "daily_charge":
                            total_consumption_cost += billing_period_usage_by_rate[rate] * billing_rates[rate]["rate"]

                    daily_cost = billing_period_usage_by_rate["daily_charge"] * billing_rates.get("daily_charge", {}).get("rate", 0)

                    final_ratio = (
                        (amount_paid - daily_cost) / total_consumption_cost
                        if total_consumption_cost
                        else 1
                    )
                    _LOGGER.debug("Final ratio: %.2f", final_ratio)


                    # Store all values, so the sensors get pull them out when needed
                    await self._stores["sensors"].async_save({
                        **self._stores["sensors"].data,
                        'historical': {
                            'historical_usage_total': usage_sensor_total,
                            'historical_cost_total': cost_sensor_total,
                            **{
                                f"historical_usage_{key}": value for key, value in usage_sensor_by_rate.items()
                            },
                            **{
                                f"historical_cost_{key}": value for key, value in cost_sensor_by_rate.items()
                            }                        
                        },
                        'regular': {
                            'billing_period_cost_total_nominal': billing_period_cost,
                            'billing_period_cost_total_effective': amount_paid,
                            'billing_period_usage_total': billing_period_usage,
                            **{f"billing_period_usage_{key}": value
                                        for key, value in billing_period_usage_by_rate.items()},
                            **{f"effective_unit_cost_{key}": value.get("rate") * final_ratio
                                        for key, value in billing_rates.items() if key != 'daily_charge'},
                            'effective_cost_ratio': final_ratio,
                        }
                    })
                    await self._stores["state"].async_save({
                        **self._stores["state"].data,
                        "last_processed_date": self._stores["state"].data.get("last_usage_date")
                    })
                    self._process_usage_data = False

                    _LOGGER.debug("Done processing data")
                else:
                    _LOGGER.debug("Inconsistent billing dates, can't process data")
            # else:
            #     _LOGGER.debug("No new data to process (flag not set)")
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Unable to process usage data")
            raise
        
    async def get_rate_types(self) -> dict[str, Any]:
        """Return the configured rate types for this property."""

        return await self._api_client.get_rate_types(
            self._account_id, self._property_id
        )

    async def get_historical_data(self, type: str) -> dict[str, Any]:
        """Return historical sensor data keyed by Unix timestamp."""

        historical_data = self._stores["sensors"].data.get("historical",{}).get(type,{})
        historical_data_filtered = {}

        #check if we have data for this historical sensor
        if historical_data:

            start_timestamp = datetime.fromisoformat(self._stores["state"].data.get(f"last_timestamp_{type}", datetime.combine(date(1970,1,1), time.min, tzinfo=dt_util.get_time_zone("Pacific/Auckland")).isoformat()))

            for timestamp, value in historical_data.items():

                ts = datetime.fromisoformat(timestamp)
                if ts >= start_timestamp:
                    historical_data_filtered[float(ts.timestamp())] = value
                    last_timestamp = ts
            
            await self._stores["state"].async_save({
                **self._stores["state"].data,
                f"last_timestamp_{type}": last_timestamp.isoformat()
            })

        # await self._stores["usage"].async_save({})
        return historical_data_filtered
