import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, DEFAULT_PORT


class SmartDrinkFridgeConfigFlow(
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    """Handle a config flow for Smart Drink Fridge."""

    VERSION = 1

    async def _validate_connection(self, host, port):
        """Validate connection to Smart Drink Fridge."""

        session = async_get_clientsession(self.hass)

        try:
            async with session.get(
                f"http://{host}:{port}/api/status",
                timeout=5,
            ) as response:
                if response.status != 200:
                    return None

                data = await response.json()

                if data.get("status") != "ok":
                    return None

                return data

        except Exception:
            return None

    async def async_step_user(self, user_input=None):
        """Handle manual setup."""

        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            data = await self._validate_connection(host, port)

            if data is None:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"{host}:{port}")
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=data.get("name", "Smart Drink Fridge"),
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(
                        CONF_PORT,
                        default=DEFAULT_PORT,
                    ): int,
                }
            ),
            errors=errors,
        )

    async def async_step_zeroconf(self, discovery_info):
        """Handle Zeroconf discovery."""

        host = str(discovery_info.ip_address)
        port = discovery_info.port

        await self.async_set_unique_id(f"{host}:{port}")
        self._abort_if_unique_id_configured()

        data = await self._validate_connection(host, port)

        if data is None:
            return self.async_abort(reason="cannot_connect")

        self._discovered_host = host
        self._discovered_port = port
        self._discovered_name = data.get(
            "name",
            "Smart Drink Fridge",
        )

        self.context["title_placeholders"] = {
            "name": self._discovered_name,
        }

        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input=None):
        """Confirm a discovered Smart Drink Fridge."""

        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered_name,
                data={
                    CONF_HOST: self._discovered_host,
                    CONF_PORT: self._discovered_port,
                },
            )

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name": self._discovered_name,
                "host": self._discovered_host,
            },
        )
