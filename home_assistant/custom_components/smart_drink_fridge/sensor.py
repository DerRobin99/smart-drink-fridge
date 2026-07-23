from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN

SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Smart Drink Fridge stock sensors."""

    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]

    session = async_get_clientsession(hass)

    async with session.get(
        f"http://{host}:{port}/api/products",
        timeout=10,
    ) as response:
        response.raise_for_status()
        products_data = await response.json()

    products = products_data.get("products", [])

    entities = [
        SmartDrinkFridgeStockSensor(
            session=session,
            host=host,
            port=port,
            product=product,
        )
        for product in products
    ]

    async_add_entities(entities, True)


class SmartDrinkFridgeStockSensor(SensorEntity):
    """Stock sensor for one Smart Drink Fridge product."""

    _attr_native_unit_of_measurement = "Stück"
    _attr_icon = "mdi:bottle-soda"

    def __init__(self, session, host, port, product):
        self._session = session
        self._host = host
        self._port = port
        self._product = product

        product_id = product["id"]
        brand = product.get("brand") or ""
        name = product.get("name") or f"Product {product_id}"
        packaging = product.get("packaging") or ""

        title = " ".join(
            value for value in [brand, name, packaging] if value
        )

        self._attr_name = title
        self._attr_unique_id = (
            f"smart_drink_fridge_{host}_{port}_{product_id}_stock"
        )

        self._attr_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, f"{host}:{port}")
            },
            name="Smart Drink Fridge",
            manufacturer="Smart Drink Fridge",
            model="Smart Drink Fridge",
            configuration_url=f"http://{host}:{port}",
        )

        self._attr_extra_state_attributes = {
            "product_id": product_id,
            "brand": brand,
            "product": name,
            "packaging": packaging,
        }

    async def async_update(self):
        """Fetch current stock."""

        async with self._session.get(
            f"http://{self._host}:{self._port}/api/stock",
            timeout=10,
        ) as response:
            response.raise_for_status()
            data = await response.json()

        product_id = self._product["id"]

        for item in data.get("stock", []):
            if item.get("product_id") == product_id:
                self._attr_native_value = item.get("stock")
                return

        self._attr_native_value = None
