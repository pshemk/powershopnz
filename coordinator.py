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
        """Schedule background usage fetching."""

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

        #run first isage processing here, once HA is up
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
        """Start a usage-processing task when none is already running, wait otherwise."""

        while  self._usage_process_task is not None and not self._usage_process_task.done():
            _LOGGER.debug("Usage process is  already running, sleeping for a bit")
            asyncio.sleep(10)
        
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

    def _get_powerpacks(self, day: str) -> list[dict[str, Any]]:
        if self._stores["powerpacks"].data.get(day, {}).get("type", "") == "list":
            _LOGGER.debug("getting a list %s", day )
            return self._stores["powerpacks"].data.get(day, {}).get("powerpacks", [])

        if self._stores["powerpacks"].data.get(day, {}).get("type", "") == "reference":
            _LOGGER.debug("getting a reference to %s from %s", self._stores["powerpacks"].data.get(day, {}).get("same_as", ""), day)
            return self._stores["powerpacks"].data.get(self._stores["powerpacks"].data.get(day, {}).get("same_as", ""), {}).get("powerpacks", [])  

    def _str_to_timestamp(self, data: dict[str, str]) -> dict[str, datetime]:
        """Convert stored ISO timestamp strings into datetime objects."""

        return {
            k: datetime.fromisoformat(v)
            for k, v in data.items() if isinstance(v, str)
        }

    def _any_to_timestamp(self, in_timestamp: str) -> datetime:
        if isinstance(in_timestamp, datetime):
            return in_timestamp
        if isinstance(in_timestamp, (str)):
            return datetime.fromisoformat(in_timestamp)
        if isinstance(in_timestamp, (int, float)):
            return datetime.fromtimestamp(in_timestamp, dt_util.get_time_zone("Pacific/Auckland"))
        
        _LOGGER.debug("Can't convert date of type %s", type(in_timestamp))
        return datetime.fromtimestamp(0, dt_util.get_time_zone("Pacific/Auckland"))
 
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

                if not self._stores["powerpacks"].data  or refresh_powerpacks:
                    #get all powerpacks
                    _LOGGER.debug("Updating powerpacks")
                    powerpacks_by_date = {}
                    powerpacks = await self._api_client.get_powerpacks(self._account_id)

                    #get all powerpacks for both previous and current billing periods
                    day = self._any_to_timestamp(self._stores["billing_dates"].data.get("previous", {}).get("datetime", {}).get("billing_period_start_date", "2100-01-01T00:00:00+00:00")).replace(hour=0, minute=0, second=0)

                    last_balance = 0
                    last_day = ""
                    while day < now: 
                        
                        powerpacks_purchased = []
                        balance = 0
                        
                        for powerpack in powerpacks:
                            if datetime.fromisoformat(powerpack["purchasedAt"]) < day:
                                balance += powerpack["balance"]
                                powerpacks_purchased.append(powerpack)

                        powerpacks_purchased.sort(key=lambda x: x['ratio'], reverse=False)
                        if balance != last_balance:
                            powerpacks_by_date[day.strftime("%Y-%m-%d")] = {
                                "type": "list",
                                "powerpacks": powerpacks_purchased
                            }
                            last_balance = balance
                            last_day = day.strftime("%Y-%m-%d")
                        else:
                            powerpacks_by_date[day.strftime("%Y-%m-%d")] = {
                                "type": "reference",
                                "same_as": last_day
                            }
                        day += timedelta(days=1)

                    await self._stores["powerpacks"].async_save(powerpacks_by_date)

                    #force reprocessing of the billing data
                    await self._schedule_usage_process()
                

                    
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
                **{ f"current_{key}": value for key, value in self._str_to_timestamp(self._stores["billing_dates"].data.get("current", {}).get("datetime")).items() },
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
                await self._schedule_usage_process()
            else:
                #only fetch new data (4 days earlier than last recorded, to allow for filling in the gaps)
                last_usage_date = (datetime.strptime(self._stores["state"].data.get("last_usage_date"), "%Y-%m-%d") - timedelta(days=4)).strftime("%Y-%m-%d")
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
                        await self._schedule_usage_process()

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

            _LOGGER.debug("Data to process")
            _LOGGER.debug(
                "Latest usage: %s, processed up to: %s",
                self._stores["state"].data.get("last_usage_date"),
                self._stores["state"].data.get("last_processed_date"),
            )

            #Determine the start and end of the current billing period                
            current_billing_period_start = self._any_to_timestamp(self._stores["billing_dates"].data.get("current", {}).get("datetime", {}).get("billing_period_start_date", "2100-01-01T00:00:00+00:00"))
            current_billing_period_end = self._any_to_timestamp(self._stores["billing_dates"].data.get("current", {}).get("datetime", {}).get("billing_period_end_date", "1970-01-01T00:00:00+00:00"))

            #Determine the start and end of the previous billing period                
            previous_billing_period_start = self._any_to_timestamp(self._stores["billing_dates"].data.get("previous", {}).get("datetime", {}).get("billing_period_start_date", "2100-01-01T00:00:00+00:00"))
            previous_billing_period_end = self._any_to_timestamp(self._stores["billing_dates"].data.get("previous", {}).get("datetime", {}).get("billing_period_end_date", "1970-01-01T00:00:00+00:00"))


            _LOGGER.debug(f"billing period start: {current_billing_period_start.isoformat()} billing period end: {current_billing_period_end.isoformat()}")                
            #make sure we have the start and end dates in the right order
            if current_billing_period_start < current_billing_period_end:
                current_billing_period_month = current_billing_period_start.strftime("%m")
                current_billing_period_usage = 0
                current_billing_period_cost = 0
                current_billing_period_usage_by_rate = {
                    rate: 0
                    for rate in self._stores["rates"].data.get(
                        current_billing_period_month, {}
                    ).keys()
                }
                current_billing_period_usage_by_rate.setdefault("daily_charge", 0)

                #Usage - stores per 1h consumption, the timeslot is the 30min in the middle of the hour
                #we fetch 30mins intervals, so two have to be summed up
                #also calulcate the sum for current billing period
                usage_sensor_total = {}

                usage_sensor_by_rate = {
                    rate: {}
                    for rate in self._stores["rates"].data.get(
                        current_billing_period_month, {}
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

                    if current_billing_period_start <= hour_timestamp < current_billing_period_end:
                        current_billing_period_usage += value
                        current_billing_period_usage_by_rate[timeslot] = (
                            current_billing_period_usage_by_rate.get(timeslot, 0) + value
                        )
                        if timestamp.date() != last_seen_date:
                            last_seen_date = timestamp.date()
                            current_billing_period_usage_by_rate["daily_charge"] += 1


                #Cost - each 30mins segment must be costed indepedently and than the hour must be summed up
                #also calulcate the sum for current billing period
                cost_sensor_total = {}

                cost_sensor_by_rate = {
                    rate: {}
                    for rate in self._stores["rates"].data.get(
                        current_billing_period_month, {}
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

                        if current_billing_period_start <= hour_timestamp < current_billing_period_end:
                            current_billing_period_cost += unit_cost * value + daily_charge / 48

                _LOGGER.debug(f"getting powerpacks for: {last_seen_date.strftime("%Y-%m-%d")}")
                #Determine effective costs, by using the purchased powerpacks
                try:
                    powerpacks = list.copy(self._get_powerpacks(last_seen_date.strftime("%Y-%m-%d")))
                    # _LOGGER.debug(f"powerpacks: {powerpacks}")

                    current_amount_paid = 0
                    total_cost = current_billing_period_cost
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
                        current_amount_paid += offset * powerpack["ratio"]
                    
                    _LOGGER.debug("Total paid for powerpacks: $%.2f", current_amount_paid)
                    
                    if total_cost > 0:
                        current_amount_paid += total_cost
                    
                    total_consumption_cost = 0
                    current_billing_rates = self._stores["rates"].data.get(current_billing_period_month, {})
                    for rate in current_billing_rates:
                        if rate != "daily_charge":
                            total_consumption_cost += current_billing_period_usage_by_rate[rate] * current_billing_rates[rate]["rate"]

                    current_daily_cost = current_billing_period_usage_by_rate["daily_charge"] * current_billing_rates.get("daily_charge", {}).get("rate", 0)

                    current_final_ratio = (
                        (current_amount_paid - current_daily_cost) / total_consumption_cost
                        if total_consumption_cost
                        else 1
                    )
                    _LOGGER.debug("Final ratio: %.2f", current_final_ratio)
                except TypeError (e):
                    _LOGGER.debug(f"Can't use powerpacks data: {e}")

            _LOGGER.debug(f"previous billing period start: {previous_billing_period_start.isoformat()} billing period end: {previous_billing_period_end.isoformat()}")                
            #make sure we have the start and end dates in the right order
            if previous_billing_period_start < previous_billing_period_end:
                previous_billing_period_month = previous_billing_period_start.strftime("%m")
                previous_billing_period_usage = 0
                previous_billing_period_cost = 0
                previous_billing_period_usage_by_rate = {
                    rate: 0
                    for rate in self._stores["rates"].data.get(
                        previous_billing_period_month, {}
                    ).keys()
                }
                previous_billing_period_usage_by_rate.setdefault("daily_charge", 0)

                #Usage - stores per 1h consumption, the timeslot is the 30min in the middle of the hour
                #we fetch 30mins intervals, so two have to be summed up
                #also calulcate the sum for current billing period

                last_seen_date = None
                for ts, value in self._stores["usage"].data.items():
                    timestamp = datetime.fromisoformat(ts)
                    hour_timestamp = timestamp.replace(
                        minute=30, second=0, microsecond=0
                    )
                    hour_ts = hour_timestamp.isoformat()
                    timeslot = self._stores["rates_schedule"].data[
                        timestamp.weekday()
                    ][timestamp.hour * 2 + timestamp.minute // 30]

                    if previous_billing_period_start <= hour_timestamp < previous_billing_period_end:
                        previous_billing_period_usage += value
                        previous_billing_period_usage_by_rate[timeslot] = (
                            previous_billing_period_usage_by_rate.get(timeslot, 0) + value
                        )
                        if timestamp.date() != last_seen_date:
                            last_seen_date = timestamp.date()
                            previous_billing_period_usage_by_rate["daily_charge"] += 1


                #Cost - each 30mins segment must be costed indepedently and than the hour must be summed up
                #also calulcate the sum for the previous billing period

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

                        if previous_billing_period_start <= hour_timestamp < previous_billing_period_end:
                            previous_billing_period_cost += unit_cost * value + daily_charge / 48

                _LOGGER.debug(f"getting powerpacks for: {last_seen_date.strftime("%Y-%m-%d")}")
                #Determine effective costs, by using the purchased powerpacks
                try:
                    powerpacks = list.copy(self._get_powerpacks(last_seen_date.strftime("%Y-%m-%d")))
                    # _LOGGER.debug(f"powerpacks: {powerpacks}")

                    previous_amount_paid = 0
                    previous_total_cost = previous_billing_period_cost
                    while previous_total_cost > 0 and len(powerpacks) > 0:
                        powerpack = powerpacks.pop(0)
                        if datetime.strptime(powerpack["availableFrom"], "%Y-%m-%d")  > datetime.now():
                            continue
                        if powerpack['balance'] <= 0:
                            continue
                        offset = min(powerpack['balance'], previous_total_cost)
                        _LOGGER.debug(
                            "Using %s to offset $%.2f of the cost, ratio: %.2f",
                            powerpack["name"],
                            offset,
                            powerpack["ratio"],
                        )
                        previous_total_cost -= offset
                        previous_amount_paid += offset * powerpack["ratio"]
                    
                    _LOGGER.debug("Total paid for powerpacks: $%.2f", previous_amount_paid)
                    
                    if previous_total_cost > 0:
                        previous_amount_paid += previous_total_cost
                    
                    previous_total_consumption_cost = 0
                    previous_billing_rates = self._stores["rates"].data.get(previous_billing_period_month, {})
                    for rate in previous_billing_rates:
                        if rate != "daily_charge":
                            previous_total_consumption_cost += previous_billing_period_usage_by_rate[rate] * previous_billing_rates[rate]["rate"]

                    previous_daily_cost = previous_billing_period_usage_by_rate["daily_charge"] * previous_billing_rates.get("daily_charge", {}).get("rate", 0)

                    previous_final_ratio = (
                        (previous_amount_paid - previous_daily_cost) / previous_total_consumption_cost
                        if previous_total_consumption_cost
                        else 1
                    )
                    _LOGGER.debug("Previous Final ratio: %.2f", previous_final_ratio)
                except TypeError (e):
                    _LOGGER.debug(f"Can't use powerpacks data: {e}")

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
                        'billing_period_cost_total_nominal': current_billing_period_cost,
                        'billing_period_cost_total_effective': current_amount_paid,
                        'billing_period_usage_total': current_billing_period_usage,
                        'previous_billing_period_cost_total_nominal': previous_billing_period_cost,
                        'previous_billing_period_cost_total_effective': previous_amount_paid,
                        'previous_billing_period_usage_total': previous_billing_period_usage,
                        **{f"billing_period_usage_{key}": value
                                    for key, value in current_billing_period_usage_by_rate.items()},
                        **{f"effective_unit_cost_{key}": value.get("rate") * current_final_ratio
                                    for key, value in current_billing_rates.items() if key != 'daily_charge'},
                        'effective_cost_ratio': current_final_ratio,
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
