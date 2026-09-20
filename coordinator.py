"""Powershop NZ data coordinator."""

from __future__ import annotations

from datetime import date, time, timedelta, datetime
import logging
import asyncio
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
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
    CONF_EMAIL,
    CONF_PROPERTY_ID,
    CONF_PROPERTY_ADDRESS,
    CONF_REFRESH_TOKEN,
    CONF_UPDATE_INTERVAL,
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
    "config",
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

        self._cancel_usage_fetch_schedule = None

        self.apiClient = PowershopApiClient(self.refresh_token)

    async def _async_setup(self) -> None:
        _LOGGER.debug("_async_setup")

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

    async def _schedule_usage_fetch(self, *args) -> None:
        _LOGGER.debug("scheduling fetch task")
        if  self._usage_fetch_task is not None and not self._usage_fetch_task.done():
            _LOGGER.debug("Usage fetch already running")
            return

        self._usage_fetch_task = self.hass.async_create_task(
            self._async_update_usage()
        )

    async def async_shutdown(self) -> None:
        if self._usage_fetch_task:
            self._usage_fetch_task.cancel()
            self._usage_fetch_task = None

        await self.apiClient.disconnect()        

    async def async_load_stores(self) -> None:
        """Load all persistent stores."""

        await asyncio.gather(
            *(store.async_load() for store in self._stores.values())
        )

    def _str_to_timestamp(self, data: Dict[str:str]) -> Dict[str:datetime]:
        return {
            k: datetime.fromisoformat(v)
            for k, v in data.items() if isinstance(v, str)
        }

    async def _async_update_data(
        self,
    ) -> dict[str, Any]:
        """Getting data to supply to sensors."""

        try:
            # _LOGGER.debug(f"running async_update_data")

            refresh_powerpacks = False
            refresh_rates = False


            now = dt_util.now()
            today = now.strftime("%Y-%m-%d")
            month = now.strftime("%m")

            if not self._last_api_call or self._last_api_call + timedelta(seconds=DEFAULT_API_CALL_INTERVAL) < now:
                
                _LOGGER.debug(f"calling the API")
                
                #get powerpack balances, if they changed - get powerpacks as well
                powerpacks_balances = await self.apiClient.get_powerpacks_balances(self._account_id)
                _LOGGER.debug(f"balances: current: {powerpacks_balances["powerpacks_available_balance"]} stored:{self._stores["powerpacks_balances"].data.get("powerpacks_available_balance")}")
                if powerpacks_balances["powerpacks_available_balance"] != self._stores["powerpacks_balances"].data.get("powerpacks_available_balance"):
                    _LOGGER.debug("powerpacks balance has changed, refreshing powerpacks")
                    refresh_powerpacks = True

                #store the current balances
                await self._stores["powerpacks_balances"].async_save(powerpacks_balances)

                #if this is a new day - fetch the rates (and schedules just to be safe) as well
                if self._stores["config"].data.get("last_rates_refresh") != today:
                    refresh_rates = True

                if not self._stores["powerpacks"].data  or refresh_powerpacks:
                    #get all powerpacks
                    _LOGGER.debug(f"updating powerpacks")
                    powerpacks = await self.apiClient.get_powerpacks(self._account_id)
                    powerpacks.sort(key=lambda x: x['ratio'], reverse=False)
                    await self._stores["powerpacks"].async_save(powerpacks)
                
                if refresh_rates:
                    #get rates and rates schedules/timeslots
                    _LOGGER.debug(f"updating rates")
                    rates = await self.apiClient.get_rates(self._account_id, self._property_id)
                    await self._stores["rates"].async_save({
                        **self._stores["rates"].data,
                        month: rates
                    })
                    
                    rates_schedule = await self.apiClient.get_rates_schedule(self._account_id, self._property_id)
                    await self._stores["rates_schedule"].async_save(rates_schedule)

                    #get billing dates
                    _LOGGER.debug(f"updating billing dates")
                    billing_dates = await self.apiClient.get_billing_dates(self._account_id)
                    await self._stores["billing_dates"].async_save(billing_dates)

                    await self._stores["config"].async_save({
                        **self._stores["config"].data,
                        "last_rates_refresh": today
                    })

                    
                # Store refresh_token if needed
                if self.apiClient.refresh_token != self._config_entry.data.get(CONF_REFRESH_TOKEN):
                    _LOGGER.debug(f"updating refresh_token")
                    self.hass.config_entries.async_update_entry(
                        self._config_entry,
                        data={
                            **self._config_entry.data,
                            CONF_REFRESH_TOKEN: self.apiClient.refresh_token,
                        },
                    )
                
                #store call time
                self._last_api_call = now
            

            #identify the current rate from the rate schedule and return it
            timeslot = self._stores["rates_schedule"].data[now.weekday()][now.hour * 2 + now.minute // 30]
            current_rate = self._stores["rates"].data.get(month).get(timeslot).get("rate")
            effective_current_rate = current_rate * self._stores["sensors"].data.get("regular", {}).get("effective_cost_ratio", 1)

            # _LOGGER.debug(f"current rate: {timeslot} {current_rate}")

            #Combine values of all sensors into a single dictionary to be returned
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

    def start_usage_update(self) -> None:
        """Start background usage synchronisation."""

        if self._usage_task is None or self._usage_task.done():
            self._usage_task = self.hass.async_create_task(
                self._async_update_usage()
            )

    
    async def _async_update_usage(self) -> None:
        """Synchronise usage data in the background."""

        try:
            _LOGGER.debug("Starting usage synchronisation")


            #just for now, reload the stores in case they got modified manually
            # await self.async_load_stores()            

            #check available historic data
            if not self._stores["config"].data.get("last_usage_date"):
                #no historic data has been retrived yet
                _LOGGER.debug(f"fetching all usage data, this might take a while ...")
                usage = await self.apiClient.get_usage(self._account_id, self._property_id)
                await self._stores["usage"].async_save(usage["usage"])
                await self._stores["config"].async_save({
                    **self._stores["config"].data,
                    "last_usage_date": usage["last_usage_date"]
                })
            else:
                #only fetch new data
                _LOGGER.debug(f"fetching recent usage data")
                usage = await self.apiClient.get_usage(self._account_id, self._property_id, self._stores["config"].data.get("last_usage_date"))
                if usage["usage"]:
                    await self._stores["usage"].async_save({
                        **self._stores["usage"].data,
                        **usage["usage"],
                        })
                    await self._stores["config"].async_save({
                        **self._stores["config"].data,
                        "last_usage_date": usage["last_usage_date"]
                    })
            _LOGGER.debug("Usage synchronised")
        
            #check if anything needs to processed:
            if self._stores["config"].data.get("last_usage_date") != self._stores["config"].data.get("last_processed_date"):
            # if True:
                _LOGGER.debug("New data to process")
                _LOGGER.debug(f"Latests usage: {self._stores["config"].data.get("last_usage_date")}, proccessed up to: {self._stores["config"].data.get("last_processed_date")}")

                #Determine the start and end of the current billing period                
                biliing_period_start_str = self._stores["billing_dates"].data.get("datetime", {}).get("current_billing_period_start_date", "1970-01-01T00:00:00+00:00") 
                biliing_period_end_str = self._stores["billing_dates"].data.get("datetime", {}).get("current_billing_period_end_date", "1970-01-01T00:00:00+00:00") 

                billing_period_start = 0
                billing_period_end = 0

                try: 
                    billing_period_start = datetime.fromisoformat(biliing_period_start_str)
                    billing_period_end = datetime.fromisoformat(biliing_period_end_str)
                except TypeError as e:
                    _LOGGER.warning(f"couldn't get billing period dates: {e}")
                

                _LOGGER.debug(f"billing start date: type: {type(billing_period_start)}")
                _LOGGER.debug(f"billing end date: type: {type(billing_period_end)}")


                #make sure we have the start and end dates
                if billing_period_start < billing_period_end:
                
                    billing_period_usage = 0
                    billing_period_cost = 0
                    billing_period_usage_by_rate = {
                        rate: 0 for rate in self._stores["rates"].data.get(billing_period_start.strftime("%m"), {}).keys() 
                    }

                    #Usage - stores per 1h consumption, the timeslot is the 30min in the middle of the hour
                    #we fetch 30mins intervals, so two have to be summed up
                    #also calulcate the sum for current billing period
                    usage_sensor_total = {}

                    usage_sensor_by_rate = {
                        rate: {} for rate in self._stores["rates"].data.get(billing_period_start.strftime("%m"), {}).keys() if rate != 'daily_charge' 
                    }

                    last_seen_day = None
                    for ts, value in self._stores["usage"].data.items():
                        hour_ts =  datetime.fromisoformat(ts).replace(minute=30,second=0,microsecond=0).isoformat()
                        usage_sensor_total[hour_ts] = usage_sensor_total.get(hour_ts, 0) + value
                        timeslot = self._stores["rates_schedule"].data[datetime.fromisoformat(ts).weekday()][datetime.fromisoformat(ts).hour * 2 + datetime.fromisoformat(ts).minute // 30]
                        usage_sensor_by_rate[timeslot][hour_ts] = usage_sensor_by_rate.get(timeslot).get(hour_ts, 0) + value

                        if datetime.fromisoformat(hour_ts) >= billing_period_start and datetime.fromisoformat(hour_ts) <= billing_period_end:
                            billing_period_usage += value
                            billing_period_usage_by_rate[timeslot] += value
                            if datetime.fromisoformat(ts).day != last_seen_day:
                                last_seen_day = datetime.fromisoformat(ts).day
                                billing_period_usage_by_rate["daily_charge"] += 1


                    #Cost - each 30mins segment must be costed indepedently and than the hour must be summed up
                    #also calulcate the sum for current billing period
                    cost_sensor_total = {}

                    cost_sensor_by_rate = {
                        rate: {} for rate in self._stores["rates"].data.get(billing_period_start.strftime("%m"), {}).keys() if rate != 'daily_charge' 
                    }

                    for ts, value in self._stores["usage"].data.items():
                        hour_ts =  datetime.fromisoformat(ts).replace(minute=30,second=0,microsecond=0).isoformat()

                        #determine timeslot (assume no schedule changes)
                        month = datetime.fromisoformat(ts).strftime("%m")
                        timeslot = self._stores["rates_schedule"].data[datetime.fromisoformat(ts).weekday()][datetime.fromisoformat(ts).hour * 2 + datetime.fromisoformat(ts).minute // 30]
                        unit_cost = self._stores["rates"].data.get(month, {}).get(timeslot, {}).get("rate")
                        if unit_cost:
                            cost_sensor_total[hour_ts] = cost_sensor_total.get(hour_ts, 0) + unit_cost * value + self._stores["rates"].data.get(month, {}).get("daily_charge").get("rate")/48

                            cost_sensor_by_rate[timeslot][hour_ts] = cost_sensor_by_rate.get(timeslot).get(hour_ts, 0) + unit_cost * value + self._stores["rates"].data.get(month, {}).get("daily_charge").get("rate")/48

                            if datetime.fromisoformat(hour_ts) >= billing_period_start and datetime.fromisoformat(hour_ts) <= billing_period_end:
                                billing_period_cost += unit_cost * value + self._stores["rates"].data.get(month, {}).get("daily_charge").get("rate")/48

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
                        _LOGGER.debug(f"Using {powerpack["name"]} to offset ${offset:.2f} of the cost, ratio: {powerpack["ratio"]:.2f}.")
                        total_cost -= offset
                        amount_paid += offset * powerpack["ratio"]
                    
                    _LOGGER.debug(f"Total paid for powerpacks: ${amount_paid:.2f}")
                    
                    if total_cost > 0:
                        amount_paid += total_cost
                    
                    total_consumption_cost = 0
                    for rate in self._stores["rates"].data.get(month, {}):
                        if rate != "daily_charge":
                            total_consumption_cost += billing_period_usage_by_rate[rate] * self._stores["rates"].data.get(month, {}).get(rate).get("rate")

                    daily_cost = billing_period_usage_by_rate["daily_charge"] * self._stores["rates"].data.get(month, {}).get("daily_charge").get("rate")

                    final_ratio = ( amount_paid - daily_cost ) / total_consumption_cost
                    _LOGGER.debug(f"Final ratio: {final_ratio:.2f}")

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
                                        for key, value in self._stores["rates"].data.get(month, {}).items() if key != 'daily_charge'},
                            'effective_cost_ratio': final_ratio,
                        }
                    })
                    await self._stores["config"].async_save({
                        **self._stores["config"].data,
                        "last_processed_date": self._stores["config"].data.get("last_usage_date")
                    })

                    _LOGGER.debug("Done processing new data")
                else:
                    _LOGGER.debug("Billing dates are not set")
            else:
                _LOGGER.debug("no new data to process")

        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Unable to synchronise usage data")
        

    async def get_rate_types(self) -> dict[str, Any]:
        return await self.apiClient.get_rate_types(self._account_id, self._property_id)

    async def get_historical_data(self, type: str) -> dict[str, Any]:

        historical_data = self._stores["sensors"].data.get("historical",{}).get(type,{})
        historical_data_filtered = {}

        #check if we have data for this historical sensor
        if historical_data:

            start_timestamp = datetime.fromisoformat(self._stores["config"].data.get(f"last_timestamp_{type}", datetime.combine(date(1970,1,1), time.min, tzinfo=dt_util.get_time_zone("Pacific/Auckland")).isoformat()))

            for timestamp, value in historical_data.items():

                ts = datetime.fromisoformat(timestamp)
                # if ts >= start_timestamp:
                historical_data_filtered[float(ts.timestamp())] = value
                    # last_timestamp = ts
            
            # await self._stores["config"].async_save({
            #     **self._stores["config"].data,
            #     f"last_timestamp_{type}": last_timestamp.isoformat()
            # })

        # await self._stores["usage"].async_save({})
        return historical_data_filtered
