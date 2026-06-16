"""Config flow for the NIO integration.

Setup is split into two independent adds:

1. **Vehicle** — paste a sniffed icar.nio.com status request (can run alone).
2. **Change / service orders** (optional) — paste a sniffed getTabOrder request
   (POST + query params on gateway-front-external.nio.com).
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import NioApiClient, NioApiError, NioAuthError, NioSignError
from .capture import parse_capture
from .change_api import NioChangeApiClient, NioChangeApiError, NioChangeAuthError
from .change_capture import change_unique_id, parse_change_capture
from .const import (
    CONF_CHANGE_METHOD,
    CONF_CHANGE_NAME,
    CONF_CHANGE_URL,
    CONF_COOKIE,
    CONF_ENTRY_TYPE,
    CONF_MODEL,
    CONF_QUERY,
    CONF_TOKEN,
    CONF_VEHICLE_ID,
    DEFAULT_CHANGE_INTERVAL,
    DEFAULT_CHANGE_METHOD,
    DEFAULT_DAY_END,
    DEFAULT_DAY_START,
    DEFAULT_INTERVAL_DAY,
    DEFAULT_INTERVAL_DRIVING,
    DEFAULT_INTERVAL_NIGHT,
    DEFAULT_MODEL,
    DOMAIN,
    ENTRY_TYPE_CHANGE,
    ENTRY_TYPE_VEHICLE,
    OPT_CHANGE_INTERVAL,
    OPT_DAY_END,
    OPT_DAY_START,
    OPT_INTERVAL_DAY,
    OPT_INTERVAL_DRIVING,
    OPT_INTERVAL_NIGHT,
)

_LOGGER = logging.getLogger(__name__)

CONF_CAPTURE = "capture"


def _capture_box() -> TextSelector:
    return TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True))


def _secret() -> TextSelector:
    return TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _clean(value: str) -> str:
    return value.removeprefix("Bearer ").strip()


VEHICLE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CAPTURE): _capture_box(),
        vol.Required(CONF_TOKEN): _secret(),
        vol.Optional(CONF_MODEL, default=DEFAULT_MODEL): str,
    }
)

CHANGE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CAPTURE): _capture_box(),
        vol.Required(CONF_TOKEN): _secret(),
        vol.Optional(CONF_CHANGE_NAME, default="NIO 换电记录"): str,
        vol.Optional(CONF_COOKIE, default=""): str,
        vol.Optional(
            CONF_CHANGE_METHOD,
            default=DEFAULT_CHANGE_METHOD,
        ): SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(value="POST", label="POST"),
                    SelectOptionDict(value="GET", label="GET"),
                ],
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
    }
)


async def _async_validate_vehicle(
    hass: HomeAssistant, *, token: str, vehicle_id: str, query: str
) -> str | None:
    client = NioApiClient(
        async_get_clientsession(hass),
        token=token,
        vehicle_id=vehicle_id,
        query=query,
    )
    try:
        await client.async_get_status()
    except NioSignError:
        return "invalid_sign"
    except NioAuthError:
        return "invalid_auth"
    except NioApiError:
        return "cannot_connect"
    return None


async def _async_validate_change(
    hass: HomeAssistant, *, token: str, url: str, method: str, cookie: str | None
) -> str | None:
    client = NioChangeApiClient(
        async_get_clientsession(hass),
        token=token,
        url=url,
        method=method,
        cookie=cookie or None,
    )
    try:
        await client.async_get_orders()
    except NioChangeAuthError:
        return "invalid_auth"
    except NioChangeApiError:
        return "cannot_connect"
    return None


def _vehicle_credentials_schema(entry: ConfigEntry) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_TOKEN, default=entry.data.get(CONF_TOKEN, "")): _secret(),
            vol.Optional(CONF_CAPTURE, default=""): _capture_box(),
        }
    )


def _change_credentials_schema(entry: ConfigEntry) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_TOKEN, default=entry.data.get(CONF_TOKEN, "")): _secret(),
            vol.Optional(CONF_CAPTURE, default=""): _capture_box(),
            vol.Optional(CONF_COOKIE, default=entry.data.get(CONF_COOKIE, "")): str,
        }
    )


class NioConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle config + reauth for NIO vehicle and service-order entries."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user",
            menu_options=["vehicle", "change"],
        )

    async def async_step_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            token = _clean(user_input[CONF_TOKEN])
            model = user_input.get(CONF_MODEL, DEFAULT_MODEL)
            try:
                vehicle_id, query = parse_capture(user_input[CONF_CAPTURE])
            except ValueError:
                errors["base"] = "invalid_url"
            else:
                await self.async_set_unique_id(vehicle_id)
                self._abort_if_unique_id_configured()
                error = await _async_validate_vehicle(
                    self.hass, token=token, vehicle_id=vehicle_id, query=query
                )
                if error is None:
                    return self.async_create_entry(
                        title=f"NIO {model}",
                        data={
                            CONF_ENTRY_TYPE: ENTRY_TYPE_VEHICLE,
                            CONF_TOKEN: token,
                            CONF_VEHICLE_ID: vehicle_id,
                            CONF_QUERY: query,
                            CONF_MODEL: model,
                        },
                    )
                errors["base"] = error

        return self.async_show_form(
            step_id="vehicle",
            data_schema=VEHICLE_SCHEMA,
            errors=errors,
        )

    async def async_step_change(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            token = _clean(user_input[CONF_TOKEN])
            name = (user_input.get(CONF_CHANGE_NAME) or "NIO 换电记录").strip()
            cookie = (user_input.get(CONF_COOKIE) or "").strip() or None
            method = user_input.get(CONF_CHANGE_METHOD, DEFAULT_CHANGE_METHOD)
            try:
                url, captured_method = parse_change_capture(user_input[CONF_CAPTURE])
            except ValueError:
                errors["base"] = "invalid_change_url"
            else:
                if method == DEFAULT_CHANGE_METHOD and captured_method != DEFAULT_CHANGE_METHOD:
                    method = captured_method
                uid = change_unique_id(url)
                await self.async_set_unique_id(uid)
                self._abort_if_unique_id_configured()
                error = await _async_validate_change(
                    self.hass,
                    token=token,
                    url=url,
                    method=method,
                    cookie=cookie,
                )
                if error is None:
                    return self.async_create_entry(
                        title=name,
                        data={
                            CONF_ENTRY_TYPE: ENTRY_TYPE_CHANGE,
                            CONF_TOKEN: token,
                            CONF_CHANGE_URL: url,
                            CONF_CHANGE_METHOD: method,
                            CONF_CHANGE_NAME: name,
                            **({CONF_COOKIE: cookie} if cookie else {}),
                        },
                    )
                errors["base"] = error

        return self.async_show_form(
            step_id="change",
            data_schema=CHANGE_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        is_change = entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_CHANGE

        if user_input is not None:
            if is_change:
                data, error = self._apply_change_credentials(entry, user_input)
                if error:
                    errors["base"] = error
                else:
                    error = await _async_validate_change(
                        self.hass,
                        token=data[CONF_TOKEN],
                        url=data[CONF_CHANGE_URL],
                        method=data.get(CONF_CHANGE_METHOD, DEFAULT_CHANGE_METHOD),
                        cookie=data.get(CONF_COOKIE),
                    )
            else:
                data, error = self._apply_vehicle_credentials(entry, user_input)
                if error:
                    errors["base"] = error
                else:
                    error = await _async_validate_vehicle(
                        self.hass,
                        token=data[CONF_TOKEN],
                        vehicle_id=data[CONF_VEHICLE_ID],
                        query=data[CONF_QUERY],
                    )
            if not errors:
                if error is None:
                    return self.async_update_reload_and_abort(entry, data=data)
                errors["base"] = error

        schema = (
            _change_credentials_schema(entry)
            if is_change
            else _vehicle_credentials_schema(entry)
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    def _apply_vehicle_credentials(
        entry: ConfigEntry, user_input: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        data = {**entry.data, CONF_TOKEN: _clean(user_input[CONF_TOKEN])}
        capture = (user_input.get(CONF_CAPTURE) or "").strip()
        if capture:
            try:
                vehicle_id, query = parse_capture(capture)
            except ValueError:
                return data, "invalid_url"
            data[CONF_VEHICLE_ID] = vehicle_id
            data[CONF_QUERY] = query
        return data, None

    @staticmethod
    def _apply_change_credentials(
        entry: ConfigEntry, user_input: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        data = {**entry.data, CONF_TOKEN: _clean(user_input[CONF_TOKEN])}
        cookie = (user_input.get(CONF_COOKIE) or "").strip()
        if cookie:
            data[CONF_COOKIE] = cookie
        elif CONF_COOKIE in data:
            data = {k: v for k, v in data.items() if k != CONF_COOKIE}
        capture = (user_input.get(CONF_CAPTURE) or "").strip()
        if capture:
            try:
                url, method = parse_change_capture(capture)
            except ValueError:
                return data, "invalid_change_url"
            data[CONF_CHANGE_URL] = url
            data[CONF_CHANGE_METHOD] = method
        return data, None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        if config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_CHANGE:
            return NioChangeOptionsFlow()
        return NioVehicleOptionsFlow()


def _interval(min_v: int, max_v: int, unit: str) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=min_v,
            max=max_v,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    )


class NioVehicleOptionsFlow(OptionsFlow):
    """Options for vehicle polling cadence + credentials."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init", menu_options=["intervals", "credentials"]
        )

    async def async_step_intervals(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={k: int(v) for k, v in user_input.items()}
            )

        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    OPT_INTERVAL_DRIVING,
                    default=opts.get(OPT_INTERVAL_DRIVING, DEFAULT_INTERVAL_DRIVING),
                ): _interval(1, 60, "min"),
                vol.Required(
                    OPT_INTERVAL_DAY,
                    default=opts.get(OPT_INTERVAL_DAY, DEFAULT_INTERVAL_DAY),
                ): _interval(5, 120, "min"),
                vol.Required(
                    OPT_INTERVAL_NIGHT,
                    default=opts.get(OPT_INTERVAL_NIGHT, DEFAULT_INTERVAL_NIGHT),
                ): _interval(5, 240, "min"),
                vol.Required(
                    OPT_DAY_START,
                    default=opts.get(OPT_DAY_START, DEFAULT_DAY_START),
                ): _interval(0, 23, "h"),
                vol.Required(
                    OPT_DAY_END,
                    default=opts.get(OPT_DAY_END, DEFAULT_DAY_END),
                ): _interval(0, 23, "h"),
            }
        )
        return self.async_show_form(step_id="intervals", data_schema=schema)

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.config_entry
        if user_input is not None:
            data, error = NioConfigFlow._apply_vehicle_credentials(entry, user_input)
            if error:
                errors["base"] = error
            else:
                error = await _async_validate_vehicle(
                    self.hass,
                    token=data[CONF_TOKEN],
                    vehicle_id=data[CONF_VEHICLE_ID],
                    query=data[CONF_QUERY],
                )
                if error is None:
                    self.hass.config_entries.async_update_entry(entry, data=data)
                    return self.async_create_entry(data=dict(entry.options))
                errors["base"] = error

        return self.async_show_form(
            step_id="credentials",
            data_schema=_vehicle_credentials_schema(entry),
            errors=errors,
        )


class NioChangeOptionsFlow(OptionsFlow):
    """Options for service-order polling + credentials."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init", menu_options=["interval", "credentials"]
        )

    async def async_step_interval(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={k: int(v) for k, v in user_input.items()}
            )

        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    OPT_CHANGE_INTERVAL,
                    default=opts.get(OPT_CHANGE_INTERVAL, DEFAULT_CHANGE_INTERVAL),
                ): _interval(15, 1440, "min"),
            }
        )
        return self.async_show_form(step_id="interval", data_schema=schema)

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.config_entry
        if user_input is not None:
            data, error = NioConfigFlow._apply_change_credentials(entry, user_input)
            if error:
                errors["base"] = error
            else:
                error = await _async_validate_change(
                    self.hass,
                    token=data[CONF_TOKEN],
                    url=data[CONF_CHANGE_URL],
                    method=data.get(CONF_CHANGE_METHOD, DEFAULT_CHANGE_METHOD),
                    cookie=data.get(CONF_COOKIE),
                )
                if error is None:
                    self.hass.config_entries.async_update_entry(entry, data=data)
                    return self.async_create_entry(data=dict(entry.options))
                errors["base"] = error

        return self.async_show_form(
            step_id="credentials",
            data_schema=_change_credentials_schema(entry),
            errors=errors,
        )
