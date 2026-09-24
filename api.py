"""Async client for the remote Powershop NZ API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from dateutil.relativedelta import relativedelta
import logging
from typing import Any
import uuid
from zoneinfo import ZoneInfo

import aiohttp

from .const import (
    FIREBASE_API_KEY,
    FIREBASE_REFRESH_URL,
    FIREBASE_SIGN_IN_URL,
    EMAIL_CONNECTOR_URL,
    OTP_VALIDATOR_URL,
    API_URL,
)

_LOGGER = logging.getLogger(__name__)
TIMEZONE = ZoneInfo("Pacific/Auckland")

QUERY_ACCOUNTS = """
    fragment AccountBalanceFragment on AccountType {
        balance(includeAllLedgers: true)
    }

    query accountsList($allowedBrandCodes: [BrandChoices]) {
        viewer {
            accounts(allowedBrandCodes: $allowedBrandCodes) {
            number
            status
            billingName
            ledgers {
                number
                ledgerType
            }
            ... on AccountType {
                id
                overdueBalance
                billingOptions {
                  nextBillingDate
                  currentBillingPeriodStartDate
                  currentBillingPeriodEndDate
                }
              
                properties {
                    id
                    address                  
                    meterPoints {
                        id
                        marketIdentifier
                        activeAgreement {
                            displayName
                            ruralPartner
                            ruralPartnerMemberId
                            }
                        }
                    }
                    ...AccountBalanceFragment
                }
            }
        }
    }
"""

QUERY_BILLING_DATES = """
query Account($accountNumber: String!) {
  account(accountNumber: $accountNumber) {
    billingOptions {
      nextBillingDate
      currentBillingPeriodStartDate
      currentBillingPeriodEndDate
    }
  }
}

"""
QUERY_RATES_SIMPLE =  """
    fragment AgreementFields on Agreement {
        displayName
        description
        validFrom
        validTo
        rates {
            label
            displayLabel
            hasDiscount
            formattedRateExcludingTax
            formattedRateIncludingTax
        }
    }

    query Agreements($accountNumber: String!, $propertyId: ID!) {
        account(accountNumber: $accountNumber) {
            id
            property(id: $propertyId) {
                id
                address
                meterPoints {
                    id
                    marketIdentifier
                    activeAgreement {
                        ...AgreementFields
                }
            }
        }
    }
}        
"""

QUERY_POWERPACK_BALANCES = """
query VouchersBalanceDetail($accountNumber: ID!) {
    vouchersBalanceDetail(accountNumber: $accountNumber) {
        redeemableToday
        redeemableInFuture
    }
}

"""

QUERY_RATES = """
    query GetAccountPropertyAgreements($accountNumber: String!, $propertyId: ID!) {
    account(accountNumber: $accountNumber) {
        id
        property(id: $propertyId) {
        id
        address
        meterPoints {
            id
            marketIdentifier
            networkHistory(first: 1) {
            edges {
                node {
                distributor {
                    code
                }
                }
            }
            }
            activeAgreement {
            ...AgreementFields
            }
            registers {
            identifier
            activeFrom
            activeTo
            }
        }
        }
    }
    }

    fragment AgreementFields on Agreement {
    displayName
    description
    validFrom
    validTo
    ruralPartner
    rates {
        label
        displayLabel
        hasDiscount
        rateIncludingTax
        formattedRateExcludingTax
        formattedRateExcludingTaxIncludingDiscount
        formattedRateIncludingTax
        formattedRateIncludingTaxIncludingDiscount
        bandCategory
        unitType
        touBucketName
    }
    timeOfUseSchemes {
        timeslots {
        timeslot
        activeFrom
        activeTo
        weekdays
        weekends
        saturdays
        sundays
        season {
            name
            startDay
            startMonth
            endDay
            endMonth
        }
        }
    }
    }
"""

QUERY_POWERPACKS = """
    query vouchersForAccount(
        $accountNumber: ID!
        $after: String
    ) {
    vouchersForAccount(
        accountNumber: $accountNumber
        redeemableOnly: true
        first: 20
        after: $after
        availableFromDate: "1970-01-01"
    ) {
        edgeCount
        edges {
        node {
            id
            displayName
            availableFrom
            purchasedAt
            voucherValue
            balance
            charge {
            grossAmount
            reason
            note
            displayNote
            }
            redemptions {
            claimedAt
            credit {
                grossAmount
            }
            }
        }
        }
        pageInfo {
        hasNextPage
        endCursor
        }
    }
    }
"""

QUERY_USAGE = """
    fragment MeasurementFields on MeasurementConnection {
    pageInfo {
        hasNextPage
        hasPreviousPage
        startCursor
        endCursor
    }
    totalCount
    edgeCount
    edges {
        node {
        value
        ... on IntervalMeasurementType {
            startAt
            endAt
        }
        }
    }
    }

    query measurements(
    $accountNumber: String!,
    $propertyId: ID!,
    $after: String,
    $startOn: Date,
    ) {
    account(accountNumber: $accountNumber) {
        id
        property(id: $propertyId) {
        id
        measurements(
            after: $after
            first: 100
            startOn: $startOn
            timezone: "Pacific/Auckland"
            utilityFilters: [{
            electricityFilters: {
                readingDirection: CONSUMPTION,
                readingQuality: ACTUAL,
                readingFrequencyType: THIRTY_MIN_INTERVAL
            }
            }]
        ) {
            ... on MeasurementConnection {
            ...MeasurementFields
            }
        }
        }
    }
    }
"""

class AuthError(Exception):
    """Raised when authentication fails (email not found, token expired, etc.)."""

class OTPError(Exception):
    """Raised when OTP verification fails."""

class PowershopApiClient:
    """Small client for the endpoint polled by the coordinator."""

    def __init__(
        self,
        refresh_token: str | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._session = session
        self._owns_session = session is None
        self.refresh_token = refresh_token
        self._id_token: str | None = None
        self._id_token_expiry: datetime | None = None

    async def _connect(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def disconnect(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()


    def _time_to_slot(self, value: str) -> int:
        """Convert HH:MM:SS into a 30-minute slot number (0..47)."""
        hour, minute, _ = map(int, value.split(":"))
        return hour * 2 + minute // 30

    async def _get_tokens_from_custom_token(self, custom_token: str) -> dict[str, str]:

        session = await self._connect()
        async with session.post(
            f"{FIREBASE_SIGN_IN_URL}?key={FIREBASE_API_KEY}",
            json={"token": custom_token, "returnSecureToken": True},
        ) as resp:
            data = await resp.json()
            if not resp.ok:
                raise AuthError(f"Can't get new id token: {data}")
            id_token = data["idToken"]
            refresh_token = data["refreshToken"]
            expires_in = int(data.get("expiresIn", 3600))

        self._id_token = id_token
        self.refresh_token = refresh_token
        self._id_token_expiry = datetime.now(UTC) + timedelta(seconds=expires_in - 60)
        _LOGGER.debug("Received a new ID token")
        return {"id_token": id_token, "refresh_token": refresh_token}

    async def _refresh_id_token(self) -> None:
        if not self.refresh_token:
            raise AuthError("No refresh token")
        
        session = await self._connect()
        
        async with session.post(
            f"{FIREBASE_REFRESH_URL}?key={FIREBASE_API_KEY}",
            data=f"grant_type=refresh_token&refresh_token={self.refresh_token}",
            headers={"content-type": "application/x-www-form-urlencoded"},
        ) as resp:
            data = await resp.json()
            if not resp.ok:
                raise AuthError(f"Token refresh failed: {data}")
            self._id_token = data["id_token"]
            self.refresh_token = data["refresh_token"]
            expires_in = int(data.get("expires_in", 3600))
            self._id_token_expiry = datetime.now(UTC) + timedelta(seconds=expires_in - 60)
            _LOGGER.debug("Refreshed ID token")

    async def _get_current_token(self) -> str:
        if (
            self._id_token is None
            or self._id_token_expiry is None
            or datetime.now(UTC) >= self._id_token_expiry
        ):
            _LOGGER.debug("Refreshing ID token")
            await self._refresh_id_token()
        if self._id_token is None:
            raise AuthError("ID token refresh returned no token")
        return self._id_token

    async def send_otp(self, email: str) -> str:

        journey_id = str(uuid.uuid4())
        session = await self._connect()
        payload = {
            "email": email,
            "brand": "powershop",
            "redirectUrl": "https://app.powershop.nz",
            "journeyId": journey_id,
            "otpEnabled": True,
        }
        async with session.post(
            EMAIL_CONNECTOR_URL,
            json=payload,
            headers={"content-type": "application/json", "X-Client-Platform": "web"},
        ) as resp:
            if resp.status == 404:
                raise AuthError("Powershop account not found")
            if not resp.ok:
                raise AuthError(f"Failed to send OTP: HTTP {resp.status}")
        return journey_id

    async def verify_otp(self, email: str, otp: str, journey_id: str) -> dict[str, str]:

        _LOGGER.debug("verify otp start")
        session = await self._connect()
        payload = {
            "email": email,
            "otp": otp,
            "brand": "powershop",
            "journeyId": journey_id,
        }
        async with session.post(
            OTP_VALIDATOR_URL,
            json=payload,
            headers={"content-type": "application/json", "X-Client-Platform": "web"},
        ) as resp:
            data = await resp.json()
            if not resp.ok:
                _LOGGER.debug("OTP Failed")
                raise OTPError(data.get("error", "OTP verification failed"))
            custom_token = data.get("customToken")
            if not custom_token:
                _LOGGER.debug("no OTP token returned")
                raise OTPError("No custom token returned by OTP validator")

        _LOGGER.debug("OTP token returned ok")
        return await self._get_tokens_from_custom_token(custom_token)


    def _billing_day_start(self, timestamp: str | None) -> str | None:
        if timestamp is None:
            return None

        dt = datetime.fromisoformat(timestamp)

        if dt.time() == datetime.min.time():
            start = dt
        else:
            start = (dt - timedelta(days=1)).replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        return start.strftime("%Y-%m-%d")

    async def _run_query(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:

        id_token = await self._get_current_token()
        session = await self._connect()
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables
        # _LOGGER.debug(f"payload: \n {payload}")
        async with session.post(
            API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {id_token}",
                "content-type": "application/json",
            },
        ) as resp:
            body = await resp.text()
            if not resp.ok:
                _LOGGER.error(f"GraphQL {resp.status}:  {body}" )
                raise ValueError(f"GraphQL HTTP {resp.status}: {body[:500]}")
            data = await resp.json(content_type=None)
        if "errors" in data:
            _LOGGER.warning("GraphQL errors: %s", data["errors"])
            raise ValueError(data["errors"][0].get("message", "GraphQL error"))
        # _LOGGER.debug(f"GraphQL data: {body}")            
        return data.get("data", {})


    async def get_properties(self) -> list[dict[str, Any]]:
        accounts = await self._run_query(
            QUERY_ACCOUNTS
        )
        properties = []
        for account in accounts.get("viewer").get("accounts"):
            _LOGGER.debug(f"account: {account}")
            for property in account.get("properties", []):
                _LOGGER.debug(f"property: {property}")
                meter_points = []
                for meter_point in property.get("meterPoints", []):
                    meter_points.append({"id": meter_point["id"], "market_identifier": meter_point["marketIdentifier"]})
                properties.append({
                    "property_id": property["id"],
                    "account_id": account.get("number"),
                    "address": " ".join(property["address"].lower().title().splitlines()),
                    "meter_points": meter_points 
                })
        _LOGGER.debug(f"got list of properties: {properties}")
        return properties


    async def get_rate_types(self, account_id: str, property_id: str) -> dict[str, Any]:
        rates_data =  await self._run_query(
            QUERY_RATES, {"accountNumber": account_id, "propertyId": property_id}
        )
        rate_types = {}
        meter_points = rates_data.get("account", {}).get("property", {}).get("meterPoints", {})
        if not meter_points or len(meter_points) == 0: 
            _LOGGER.warning("Can not find any meters")
            return {}
        rates = meter_points[0].get("activeAgreement", {}).get("rates", {})
        if not rates or len(rates) == 0:
            _LOGGER.warning("Can not find any rates")
            return {}
        for rate in rates:
            bucket = rate.get("touBucketName")
            display_label = rate.get("displayLabel")
            if not bucket or not display_label:
                continue

            key = display_label.replace(" ", "_").lower()
            rate_value = float(rate["rateIncludingTax"]) / 100
            existing_rate = rate_types.get(key)
            if existing_rate and (
                existing_rate["bucket"] != bucket
                or existing_rate["rate"] != rate_value
            ):
                _LOGGER.warning("Inconsistent rate data for %s", rate)
                continue

            rate_types[key] = {
                "name": display_label,
                "bucket": bucket,
                "rate": rate_value,
            }
        return rate_types

    async def get_rates(self, account_id: str, property_id: str) -> dict[str, Any]:
        rates_data =  await self._run_query(
            QUERY_RATES, {"accountNumber": account_id, "propertyId": property_id}
        )
        final_rates = {}
        meter_points = rates_data.get("account", {}).get("property", {}).get("meterPoints", {})
        if not meter_points or len(meter_points) == 0: 
            _LOGGER.warning("Can not find any meters")
            return {}
        rates = meter_points[0].get("activeAgreement", {}).get("rates", {})
        if not rates or len(rates) == 0:
            _LOGGER.warning("Can not find any rates")
            return {}
        for rate in rates:
                final_rates[rate.get("displayLabel").replace(" ", "_").lower()] = {
                    "name": rate.get("displayLabel"),
                    "type": rate.get("bandCategory"),
                    "rate": float(rate.get("rateIncludingTax"))/100,    #originally in cents
                }
        return final_rates


    async def get_powerpacks_balances(self, account_id: str) -> dict[str, Any]:
        balances_data = await self._run_query(
            QUERY_POWERPACK_BALANCES, {"accountNumber": account_id}
        )        
        return {
            "powerpacks_available_balance": balances_data["vouchersBalanceDetail"]["redeemableToday"]/100,
            "powerpacks_future_balance": balances_data["vouchersBalanceDetail"]["redeemableInFuture"]/100,
            }

    async def get_powerpacks(self, account_id: str) -> list[dict[str, Any]]:

        cursor = None
        powerpacks_data = []
        while True:
            powerpacks_data_raw = await self._run_query(
                QUERY_POWERPACKS, {"accountNumber": account_id, "after": cursor }
            )
            edges = powerpacks_data_raw.get("vouchersForAccount", {}).get("edges", {})
            if not edges or len(edges) == 0:
                break
            for node in edges:
                powerpacks_data.append(
                    {
                        "id": node["node"]["id"],
                        "name": node["node"]["displayName"],
                        "availableFrom": node["node"]["availableFrom"],
                        "purchasedAt": node["node"]["purchasedAt"],
                        "purchaseCost": float(node["node"]["voucherValue"])/100,
                        "ratio": float(node["node"]["charge"]["grossAmount"])/float(node["node"]["voucherValue"]),
                        "balance": float(node["node"]["balance"])/100,
                    }
                )
            page_info = powerpacks_data_raw.get("vouchersForAccount", {}).get(
                "pageInfo", {}
            )
            if not page_info.get("hasNextPage"):
                break
            next_cursor = page_info.get("endCursor")
            if not next_cursor or next_cursor == cursor:
                raise ValueError("Powerpacks pagination returned an invalid cursor")
            cursor = next_cursor
        
        # _LOGGER.debug(f"raw powerpacks data:{powerpacks_data}")
        return powerpacks_data
            

    async def get_rates_schedule(
        self, account_id: str, property_id: str
    ) -> list[list[str | None]]:

        rate_types = await self.get_rate_types(account_id, property_id)
        buckets = {}

        for rate_name, rate_type in rate_types.items():
            buckets[rate_type["bucket"]] = rate_name
        # _LOGGER.debug(f"buckets: {buckets}")    
        
        rates_data =  await self._run_query(
            QUERY_RATES, {"accountNumber": account_id, "propertyId": property_id}
        )
        meter_points = rates_data.get("account", {}).get("property", {}).get("meterPoints", {})
        if not meter_points or len(meter_points) == 0: 
            _LOGGER.debug("no meter_points")
            return []
        tous = meter_points[0].get("activeAgreement", {}).get("timeOfUseSchemes", {})
        if not tous or len(tous) == 0:
            _LOGGER.debug("no tous")
            return []
        timeslots = tous[0].get("timeslots", [])
        # _LOGGER.debug(f"timeslots: {timeslots}")
        if not timeslots or len(timeslots) == 0:
            return []
        
        rates_schedule = [[None] * 48 for _ in range(7)]

        for slot in timeslots:
            start = self._time_to_slot(slot["activeFrom"])
            end = self._time_to_slot(slot["activeTo"])

            if start == end:
                slots = range(48)
            elif start < end:
                slots = range(start, end)
            else:
                slots = list(range(start, 48)) + list(range(end))

            if slot["weekdays"]:
                weekdays = range(5)
            elif slot["saturdays"]:
                weekdays = [5]
            elif slot["sundays"]:
                weekdays = [6]
            elif slot["weekends"]:
                weekdays = [5, 6]
            else:
                weekdays = []

            for weekday in weekdays:
                for half_hour in slots:
                    if rates_schedule[weekday][half_hour] is not None:
                        raise ValueError(
                            f"Overlapping timeslots: "
                            f"{rates_schedule[weekday][half_hour]} / {buckets[slot['timeslot']]}"
                        )

                    rates_schedule[weekday][half_hour] = buckets[slot["timeslot"]]

        return rates_schedule

    async def get_usage(
        self, account_id: str, property_id: str, startOn: str | None = None
    ) -> dict[str, Any]:

        cursor = None
        usage_data = {}
        last_timestamp = None

        while True:
            usage_data_raw = await self._run_query(
                QUERY_USAGE, {"accountNumber": account_id, "propertyId": property_id, "after": cursor, "startOn": startOn }
            )
            edges = usage_data_raw.get("account", {}).get("property", {}).get("measurements", {}).get("edges", {})
            if not edges or len(edges) == 0:
                break
            for node in edges:
                usage_data[node["node"]["startAt"]] = float(node["node"]["value"])
                last_timestamp = node["node"]["endAt"]
            page_info = usage_data_raw.get("account", {}).get("property", {}).get(
                "measurements", {}
            ).get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            next_cursor = page_info.get("endCursor")
            if not next_cursor or next_cursor == cursor:
                raise ValueError("Usage pagination returned an invalid cursor")
            cursor = next_cursor
        
        return {
            "usage": usage_data,
            "last_usage_date": self._billing_day_start(last_timestamp) if last_timestamp else self._billing_day_start(startOn)
        }

    async def get_billing_dates(self, account_id: str) -> dict[str, Any]:
        billing_dates_data = await self._run_query(
            QUERY_BILLING_DATES, {"accountNumber": account_id}
        )        

        next_billing_date = billing_dates_data.get("account", {}).get("billingOptions", {}).get("nextBillingDate", "1970-01-01")
        billing_period_start_date = billing_dates_data.get("account", {}).get("billingOptions", {}).get("currentBillingPeriodStartDate", "1970-01-01")
        billing_period_end_date = billing_dates_data.get("account", {}).get("billingOptions", {}).get("currentBillingPeriodEndDate", "1970-01-01")
        return {
             "current": {
                "datetime": {
                    "next_billing_date": datetime.strptime(next_billing_date, "%Y-%m-%d").replace(tzinfo=TIMEZONE),
                    "billing_period_start_date": datetime.strptime(billing_period_start_date, "%Y-%m-%d").replace(tzinfo=TIMEZONE),
                    "billing_period_end_date": datetime.strptime(billing_period_end_date, "%Y-%m-%d").replace(tzinfo=TIMEZONE, hour=23, minute=59, second=59),
                },
                "string":{
                    "next_billing_date": next_billing_date, 
                    "billing_period_start_date": billing_period_start_date,
                    "billing_period_end_date": billing_period_end_date,
                }
            },
             "previous": {
                "datetime": {
                    "billing_period_start_date": datetime.strptime(billing_period_start_date, "%Y-%m-%d").replace(tzinfo=TIMEZONE) - relativedelta(months=1),
                    "billing_period_end_date": datetime.strptime(billing_period_end_date, "%Y-%m-%d").replace(tzinfo=TIMEZONE, hour=23, minute=59, second=59) - relativedelta(months=1),
                },
                "string":{
                    "billing_period_start_date": (datetime.strptime(billing_period_start_date, "%Y-%m-%d").replace(tzinfo=TIMEZONE) - relativedelta(months=1)).strftime("%Y-%m-%d"),
                    "billing_period_end_date": (datetime.strptime(billing_period_end_date, "%Y-%m-%d").replace(tzinfo=TIMEZONE, hour=23, minute=59, second=59) - relativedelta(months=1)).strftime("%Y-%m-%d")
                }
            }
        }
