"""Config flow for Powershop integration."""
import logging
from typing import Any, Dict, Mapping, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .api import AuthError, OTPError, PowershopApiClient
from .const import (
    CONF_ACCOUNT_ID,
    CONF_EMAIL,
    CONF_PROPERTY_ID,
    CONF_PROPERTY_ADDRESS,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class PowershopConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    
    VERSION = 1

    def __init__(self) -> None:
        self._email: Optional[str] = None
        self._journey_id: Optional[str] = None
        self._client = PowershopApiClient()
        self.user_info = {}


    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        errors: Dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip().lower()
            try:
                journey_id = await self._client.send_otp(email)
                await self._client.disconnect()
                self._email = email
                self._journey_id = journey_id
                return await self.async_step_otp()
            except AuthError:
                errors["base"] = "email_not_found"
            except Exception:
                _LOGGER.exception("Unexpected error sending OTP")
                errors["base"] = "cannot_connect"
            finally:
                await self._client.disconnect()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_EMAIL): str
            }),
            errors=errors or {},
        )

    async def async_step_otp(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        errors: Dict[str, str] = {}

        if user_input is not None:
            otp = user_input["otp"].strip()

            try:
                tokens = await self._client.verify_otp(self._email, otp, self._journey_id)

                self._client._refresh_token = tokens["refresh_token"]
                self._client._id_token = tokens["id_token"]

                self.user_info["refresh_token"] = tokens["refresh_token"]

                # Get properties            
                self.user_info["properties"] = await self._client.get_properties()
                return await self.async_step_properties()
            except OTPError:
                errors["base"] = "invalid_otp"
            except AuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected error verifying OTP")
                errors["base"] = "cannot_connect"
            finally:
                await self._client.disconnect()

        return self.async_show_form(
            step_id="otp",
            data_schema=vol.Schema({
              vol.Required("otp"): str
            }),
            errors=errors,
            description_placeholders={"email": self._email},
        )

    async def async_step_properties(self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        errors: Dict[str, str] = {}
        if user_input is not None:

            #find the account_id from the property_id
            property_id = user_input["property_id"]
            account_id = [ property["account_id"] for property in self.user_info["properties"] if property["property_id"] == property_id ][0]
            property_address = [ property["address"] for property in self.user_info["properties"] if property["property_id"] == property_id ][0]
            _LOGGER.debug(f"user_info: {self.user_info}")
            _LOGGER.debug(f"account_id: {account_id} {property_id} {property_address}")

            _LOGGER.debug("creating entry")

            return self.async_create_entry(
                title=f"Powershop NZ",
                data={
                    CONF_EMAIL: self._email,
                    CONF_REFRESH_TOKEN: self.user_info["refresh_token"],
                    CONF_ACCOUNT_ID: account_id,
                    CONF_PROPERTY_ID: property_id,
                    CONF_PROPERTY_ADDRESS: property_address,
                },
            )

        return self.async_show_form(
            step_id="properties",
            data_schema=vol.Schema({
                vol.Required(CONF_PROPERTY_ID): vol.In(
                    {
                        property["property_id"]: property["address"] for property in self.user_info["properties"]
                    }
                ),
                vol.Optional(CONF_PROPERTY_NAME): str

            }),
            errors=errors,
        )

        
    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> FlowResult:
        """Re-authenticate an existing entry (e.g. refresh token revoked)."""
        self._email = entry_data.get(CONF_EMAIL)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        errors: Dict[str, str] = {}

        if user_input is not None:
            try:
                journey_id = await self._client.send_otp(self._email)
                await self._client.disconnect()
                self._journey_id = journey_id
                return await self.async_step_reauth_otp()
            except Exception:
                _LOGGER.exception("Re-auth OTP send failed")
                errors["base"] = "cannot_connect"
            finally:
                await self._client.disconnect()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"email": self._email},
        )

    async def async_step_reauth_otp(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        errors: Dict[str, str] = {}

        if user_input is not None:
            otp = user_input["otp"].strip()
            try:
                tokens = await self._client.verify_otp(self._email, otp, self._journey_id)
                _LOGGER.debug(f"tokens: {tokens}")
                entry = self.hass.config_entries.async_get_entry(
                    self.context["entry_id"]
                )
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data,
                        CONF_REFRESH_TOKEN: tokens["refresh_token"],
                    },
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            except OTPError:
                errors["base"] = "invalid_otp"
            except Exception:
                _LOGGER.exception("Re-auth OTP verify failed")
                errors["base"] = "cannot_connect"
            finally:
                await self._client.disconnect()

        return self.async_show_form(
            step_id="reauth_otp",
            data_schema=vol.Schema({
              vol.Required("otp"): str
            }),
            errors=errors,
            description_placeholders={"email": self._email},
        )