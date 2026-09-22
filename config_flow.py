"""Config flow for Powershop integration."""

import logging
from typing import Any, Mapping, TypedDict

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import OptionsFlowWithReload
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .api import AuthError, OTPError, PowershopApiClient
from .const import (
    CONF_ACCOUNT_ID,
    CONF_EMAIL,
    CONF_PROPERTY_ID,
    CONF_PROPERTY_ADDRESS,
    CONF_REFRESH_TOKEN,
    CONF_SENSORS_GROUPS,
    CONF_REPROCESS_DATA,
    CONF_SENSORS_OPTIONS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class PropertyInfo(TypedDict):
    """Property returned by the Powershop API."""

    property_id: str
    account_id: str
    address: str


class PowershopConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Powershop configuration flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._email: str | None = None
        self._journey_id: str | None = None
        self._client = PowershopApiClient()
        self._refresh_token: str | None = None
        self._properties: list[PropertyInfo] = []
        self._selected_property: PropertyInfo | None = None

    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow."""
        return PowershopOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip().lower()
            try:
                journey_id = await self._client.send_otp(email)
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
            data_schema=vol.Schema({vol.Required(CONF_EMAIL): str}),
            errors=errors or {},
        )

    async def async_step_otp(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            otp = user_input["otp"].strip()

            try:
                if self._email is None or self._journey_id is None:
                    raise AuthError("OTP flow state is missing")
                tokens = await self._client.verify_otp(self._email, otp, self._journey_id)
                self._refresh_token = tokens["refresh_token"]

                self._properties = await self._client.get_properties()
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
            data_schema=vol.Schema(
                {vol.Required("otp"): vol.All(str, vol.Length(min=6, max=6))}
            ),
            errors=errors,
            description_placeholders={"email": self._email},
        )

    async def async_step_properties(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            properties = {
                property_data["property_id"]: property_data
                for property_data in self._properties
            }
            self._selected_property = properties[user_input[CONF_PROPERTY_ID]]
            return await self.async_step_sensors()


        return self.async_show_form(
            step_id="properties",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PROPERTY_ID): vol.In(
                        {
                            property_data["property_id"]: property_data["address"]
                            for property_data in self._properties
                        }
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if (
                self._email is None
                or self._selected_property is None
                or self._refresh_token is None
            ):
                errors["base"] = "cannot_connect"
                return self.async_show_form(
                    step_id="sensors",
                    data_schema=vol.Schema(
                        {
                            vol.Required(group, default=enabled): selector.BooleanSelector()
                            for group, enabled in CONF_SENSORS_GROUPS.items()
                        }
                    ),
                    errors=errors,
                )

            property_data = self._selected_property
            await self.async_set_unique_id(
                f"{property_data['account_id']}_{property_data['property_id']}"
            )
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title="Powershop NZ",
                data={
                    CONF_EMAIL: self._email,
                    CONF_REFRESH_TOKEN: self._refresh_token,
                    CONF_ACCOUNT_ID: property_data["account_id"],
                    CONF_PROPERTY_ID: property_data["property_id"],
                    CONF_PROPERTY_ADDRESS: property_data["address"],
                },
                options={ CONF_SENSORS_OPTIONS: user_input }
            )

        return self.async_show_form(
            step_id="sensors",
            data_schema=vol.Schema(
                {
                    vol.Required(group, default=enabled): selector.BooleanSelector()
                    for group, enabled in CONF_SENSORS_GROUPS.items()
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> FlowResult:
        """Re-authenticate an existing entry (e.g. refresh token revoked)."""
        self._email = entry_data.get(CONF_EMAIL)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                if self._email is None:
                    raise AuthError("Re-authentication email is missing")
                journey_id = await self._client.send_otp(self._email)
                self._journey_id = journey_id
                return await self.async_step_reauth_otp()
            except AuthError:
                errors["base"] = "email_not_found"
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
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            otp = user_input["otp"].strip()
            try:
                if self._email is None or self._journey_id is None:
                    raise AuthError("OTP flow state is missing")
                tokens = await self._client.verify_otp(self._email, otp, self._journey_id)
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
            data_schema=vol.Schema(
                {vol.Required("otp"): vol.All(str, vol.Length(min=6, max=6))}
            ),
            errors=errors,
            description_placeholders={"email": self._email},
        )


class PowershopOptionsFlow(OptionsFlowWithReload):
    """Handle Powershop options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self.async_step_sensors(user_input)

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:

            return self.async_create_entry(
                data={
                    **self.config_entry.options,
                    CONF_SENSORS_OPTIONS:
                    { key: value for key, value in user_input.items() if key != CONF_REPROCESS_DATA},
                    CONF_REPROCESS_DATA: bool(user_input[CONF_REPROCESS_DATA]),
                }
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    **{
                        vol.Required(group, default=enabled): selector.BooleanSelector()
                        for group, enabled in sorted(
                            self.config_entry.options.get(CONF_SENSORS_OPTIONS, CONF_SENSORS_GROUPS).items()
                        )
                    },
                    vol.Required(CONF_REPROCESS_DATA, default=self.config_entry.options.get(CONF_REPROCESS_DATA, False)): selector.BooleanSelector(),
                }
            ),
            errors=errors,
        )
