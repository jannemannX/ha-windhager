"""Support for Windhager Climate."""

from __future__ import annotations

import logging
from datetime import timedelta

import voluptuous as vol
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=60)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "set_current_temp_compensation",
        {
            vol.Required("compensation"): vol.All(
                vol.Coerce(float), vol.Range(min=-3.5, max=3.5)
            ),
        },
        "set_current_temp_compensation",
    )

    """ Set up WindHager climates from a config entry. """
    data_coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []

    for deviceInfo in data_coordinator.data.get("devices"):
        if deviceInfo.get("type") == "climate":
            entity = WindhagerThermostatClimate(data_coordinator, deviceInfo)
            entities.append(entity)
            entity = WindhagerThermostatClimateWithoutBias(data_coordinator, deviceInfo)
            entities.append(entity)

    # entity = WindhagerThermostatClimate(client, "/1/15")
    async_add_entities(entities)


class WindhagerThermostatClimate(CoordinatorEntity, ClimateEntity):
    """WindHager climate"""

    SCAN_INTERVAL = timedelta(seconds=60)

    def __init__(self, coordinator, deviceInfo):
        super().__init__(coordinator)
        self.client = self.coordinator.client
        self._id = deviceInfo.get("id")
        self._name = deviceInfo.get("name")
        self._prefix = deviceInfo.get("prefix")
        self._preset_modes = [
            "0",
            "1",
            "2",
            "3",
            "4",
            "5",
            "6",
            "7",
        ]
        self._custom_temp_remaining_time = 0
        self._attr_translation_key = "windhager_climate"
        self._device_info = DeviceInfo(
            identifiers={(DOMAIN, deviceInfo.get("device_id"))},
            name=deviceInfo.get("device_name"),
            manufacturer="Windhager",
            model=deviceInfo.get("device_name"),
        )

    @property
    def unique_id(self):
        return self._id

    @property
    def name(self):
        return self._name

    @property
    def temperature_unit(self):
        return UnitOfTemperature.CELSIUS

    @property
    def device_info(self) -> DeviceInfo:
        return self._device_info

    @property
    def supported_features(self):
        return (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

    @property
    def current_temperature(self):
        try:
            return float(
                self.coordinator.data.get("oids", {}).get(
                    self._prefix + "/0/0/1/0", "0"
                )
            ) - float(
                self.coordinator.data.get("oids", {}).get(
                    self._prefix + "/0/3/58/0", "0"
                )
            )
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Invalid current temperature value for %s, setting as None.",
                self._prefix,
            )
            return None

    @property
    def target_temperature(self):
        try:
            return float(
                self.coordinator.data.get("oids", {}).get(
                    self._prefix + "/0/1/1/0", "0"
                )
            ) - float(
                self.coordinator.data.get("oids", {}).get(
                    self._prefix + "/0/3/58/0", "0"
                )
            )
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Invalid target temperature value for %s, setting as None.",
                self._prefix,
            )
            return None

    @property
    def target_temperature_step(self):
        return 0.5

    @property
    def hvac_mode(self):
        return HVACMode.HEAT

    @property
    def hvac_action(self):
        if self.raw_preset_mode() == 0:
            return HVACAction.OFF

        return HVACAction.HEATING

    @property
    def hvac_modes(self):
        return [HVACMode.HEAT, HVACMode.OFF]

    @property
    def preset_mode(self):
        if self.raw_custom_temp_remaining_time() > 0:
            return self._preset_modes[7]

        return self._preset_modes[self.raw_preset_mode()]

    @property
    def preset_modes(self):
        return self._preset_modes

    def raw_selected_mode(self):
        try:
            return int(
                self.coordinator.data.get("oids", {}).get(self._prefix + "/0/3/50/0", 0)
            )
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Invalid selected mode value for %s, setting as None.", self._prefix
            )
            return None

    def raw_custom_temp_remaining_time(self):
        try:
            return int(
                self.coordinator.data.get("oids", {}).get(self._prefix + "/0/2/10/0", 0)
            )
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Invalid custom temp remaining time for %s, setting as None.", self._prefix
            )
            return None

    def raw_preset_mode(self):
        try:
            return int(
                self.coordinator.data.get("oids", {}).get(self._prefix + "/0/3/50/0", 0)
            )
        except (ValueError, TypeError):
            _LOGGER.warning("Invalid preset mode for %s, setting as None.", self._prefix)
            return None

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""

    async def async_set_preset_mode(self, preset_mode):
        id_mode = self._preset_modes.index(preset_mode)
        await self.client.update(self._prefix + "/0/3/50/0", str(id_mode))
        # Désactivation du mode manuel au besoin
        if self.raw_custom_temp_remaining_time() > 0:
            await self.client.update(self._prefix + "/0/2/10/0", "0")
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs):
        await self.client.update(
            self._prefix + "/0/3/4/0", str(kwargs.get(ATTR_TEMPERATURE))
        )
        # Duration of custom temperature (max 400 minutes)
        await self.client.update(self._prefix + "/0/2/10/0", "400")
        await self.coordinator.async_request_refresh()

    async def set_current_temp_compensation(self, compensation):
        await self.client.update(self._prefix + "/0/3/58/0", str(compensation))
        await self.coordinator.async_request_refresh()


class WindhagerThermostatClimateWithoutBias(CoordinatorEntity, ClimateEntity):
    """WindHager climate"""

    SCAN_INTERVAL = timedelta(seconds=60)

    def __init__(self, coordinator, deviceInfo):
        super().__init__(coordinator)
        self.client = self.coordinator.client
        self._id = deviceInfo.get("id") + "_nobias"
        self._name = deviceInfo.get("name") + " without bias"
        self._prefix = deviceInfo.get("prefix")
        self._preset_modes = [
            "0",
            "1",
            "2",
            "3",
            "4",
            "5",
            "6",
            "7",
        ]
        self._custom_temp_remaining_time = 0
        self._attr_translation_key = "windhager_climate"
        self._device_info = DeviceInfo(
            identifiers={(DOMAIN, deviceInfo.get("device_id"))},
            name=deviceInfo.get("device_name"),
            manufacturer="Windhager",
            model=deviceInfo.get("device_name"),
        )

    @property
    def unique_id(self):
        return self._id

    @property
    def name(self):
        return self._name

    @property
    def temperature_unit(self):
        return UnitOfTemperature.CELSIUS

    @property
    def device_info(self) -> DeviceInfo:
        return self._device_info

    @property
    def supported_features(self):
        return (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

    @property
    def current_temperature(self):
        try:
            return float(
                self.coordinator.data.get("oids").get(self._prefix + "/0/0/1/0", "0")
            )
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Invalid current temperature value for %s, setting as None.",
                self._prefix,
            )
            return None

    @property
    def target_temperature(self):
        try:
            return float(
                self.coordinator.data.get("oids").get(self._prefix + "/0/1/1/0")
            )
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Invalid target temperature value for %s, setting as None.",
                self._prefix,
            )
            return None

    @property
    def target_temperature_step(self):
        return 0.5

    @property
    def hvac_mode(self):
        return HVACMode.HEAT

    @property
    def hvac_action(self):
        if self.raw_preset_mode() == 0:
            return HVACAction.OFF

        return HVACAction.HEATING

    @property
    def hvac_modes(self):
        return [HVACMode.HEAT, HVACMode.OFF]

    @property
    def preset_mode(self):
        if self.raw_custom_temp_remaining_time() > 0:
            return self._preset_modes[7]

        return self._preset_modes[self.raw_preset_mode()]

    @property
    def preset_modes(self):
        return self._preset_modes

    def raw_selected_mode(self):
        try:
            return int(
                self.coordinator.data.get("oids", {}).get(self._prefix + "/0/3/50/0", 0)
            )
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Invalid selected mode value for %s, setting as None.", self._prefix
            )
            return None

    def raw_custom_temp_remaining_time(self):
        try:
            return int(
                self.coordinator.data.get("oids", {}).get(self._prefix + "/0/2/10/0", 0)
            )
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Invalid custom temp remaining time for %s, setting as None.", self._prefix
            )
            return None

    def raw_preset_mode(self):
        try:
            return int(
                self.coordinator.data.get("oids", {}).get(self._prefix + "/0/3/50/0", 0)
            )
        except (ValueError, TypeError):
            _LOGGER.warning("Invalid preset mode for %s, setting as None.", self._prefix)
            return None

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""

    async def async_set_preset_mode(self, preset_mode):
        id_mode = self._preset_modes.index(preset_mode)
        await self.client.update(self._prefix + "/0/3/50/0", str(id_mode))
        # Désactivation du mode manuel au besoin
        if self.raw_custom_temp_remaining_time() > 0:
            await self.client.update(self._prefix + "/0/2/10/0", "0")
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs):
        await self.client.update(
            self._prefix + "/0/3/4/0", str(kwargs.get(ATTR_TEMPERATURE))
        )
        # Duration of custom temperature (max 400 minutes)
        await self.client.update(self._prefix + "/0/2/10/0", "400")
        await self.coordinator.async_request_refresh()
