"""Sensor platform for Sparebank1 Pengerobot."""
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import CONF_NAME
import logging

from .const import DOMAIN, INTEGRATION_NAME, MANUFACTURER
from .coordinator import Sparebank1Coordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Sparebank1 Pengerobot sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    
    # Create the main account status sensor
    entities = [Sparebank1AccountSensor(coordinator, entry)]
    
    # Wait for initial data to create individual account sensors
    async_add_entities(entities, True)

    # Track already added account unique_ids to prevent duplicates
    added_accounts: set[str] = {
        entity.unique_id for entity in entities if isinstance(entity, Sparebank1AccountBalanceSensor)
    }

    def _handle_coordinator_update() -> None:
        """Add sensors for newly discovered accounts after a data refresh."""
        if not coordinator.data or "accounts" not in coordinator.data:
            return
        new_entities: list[Sparebank1AccountBalanceSensor] = []
        for idx, acc in enumerate(coordinator.data["accounts"]):
            acc_number = acc.get("accountNumber", f"account_{idx}")
            uniq = f"{DOMAIN}_{entry.entry_id}_account_{acc_number}"
            if uniq in added_accounts:
                continue
            new_entities.append(Sparebank1AccountBalanceSensor(coordinator, entry, acc, idx))
            added_accounts.add(uniq)
        if new_entities:
            # True → call update() immediately for fresh state
            async_add_entities(new_entities, True)

    # Listen for every successful coordinator refresh
    coordinator.async_add_listener(_handle_coordinator_update)

    # Initial account sensor discovery
    _handle_coordinator_update()


class BaseSparebank1Sensor(CoordinatorEntity, SensorEntity):
    """Base class for Sparebank1 sensors with common functionality."""
    
    def __init__(self, coordinator: Sparebank1Coordinator, entry: ConfigEntry):
        """Initialize the base sensor."""
        super().__init__(coordinator)
        self.entry = entry
    
    @property
    def device_info(self):
        """Return the device info."""
        return {
            "identifiers": {(DOMAIN, self.entry.entry_id)},
            "name": f"{INTEGRATION_NAME} {self.entry.data.get(CONF_NAME)}",
            "manufacturer": MANUFACTURER,
            "model": INTEGRATION_NAME,
        }
    
    @property
    def available(self):
        """Return if entity is available."""
        # Allow showing stale data for up to 3 hours instead of immediately going unavailable

        # If we don't have data, return False on availability immediately
        if self.coordinator.data is None:
            _LOGGER.debug("Coordinator says: No data - sensors unavailable")
            return False
            
        
        # If we have data, check if it's not too stale
        from datetime import datetime, timedelta
        last_update_str = self.coordinator.data.get("last_update")
        _LOGGER.debug("Coordinator says: Last update was: %s", last_update_str)
        if last_update_str:
            try:
                last_update = datetime.fromisoformat(last_update_str.replace('Z', '+00:00'))

                # Allow stale data for up to 3 hours (configurable)
                max_staleness = timedelta(hours=3)
                if datetime.utcnow() - last_update.replace(tzinfo=None) < max_staleness:
                    _LOGGER.debug("Coordinator says: Data is fresh enough")
                    return True
                else:
                    _LOGGER.debug("Coordinator says: Current data is stale, but we return whatever was the success state of the coordinator.")
            except (ValueError, TypeError):
                pass
        
        # Fall back to coordinator success for truly old/missing data
        return self.coordinator.last_update_success

class Sparebank1AccountSensor(BaseSparebank1Sensor):
    """Sensor representing Sparebank1 account status."""
    
    def __init__(self, coordinator: Sparebank1Coordinator, entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_accounts"
        self._attr_name = f"{entry.data.get(CONF_NAME)} Accounts"
        self._attr_icon = "mdi:bank"
        
    @property
    def native_value(self):
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None
        
        accounts = self.coordinator.data.get("accounts", [])
        return len(accounts)
    
    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement."""
        return None  # No unit for count sensors
    
    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        if not self.coordinator.data:
            return {}
        
        accounts = self.coordinator.data.get("accounts", [])
        last_update = self.coordinator.data.get("last_update")
        
        attributes = {
            "integration_id": self.entry.entry_id,
            "account_count": len(accounts),
            "last_update": last_update,
        }
        
        # Add information about partial balance fetches or errors
        if self.coordinator.data.get("balance_fetch_partial"):
            attributes["balance_fetch_status"] = "partial_failure"
            balance_errors = self.coordinator.data.get("balance_fetch_errors", [])
            if balance_errors:
                attributes["balance_fetch_errors"] = balance_errors[:3]  # Limit to first 3 errors
        else:
            attributes["balance_fetch_status"] = "success"
        
        return attributes


class Sparebank1AccountBalanceSensor(BaseSparebank1Sensor):
    """Sensor representing individual Sparebank1 account balance."""
    
    def __init__(self, coordinator: Sparebank1Coordinator, entry: ConfigEntry, account: dict, account_index: int):
        """Initialize the account balance sensor."""
        super().__init__(coordinator, entry)
        self.account_data = account
        self.account_index = account_index
        
        account_number = account.get("accountNumber", f"account_{account_index}")
        account_name = account.get("name", f"Account {account_index + 1}")
        
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_account_{account_number}"
        self._attr_name = f"{entry.data.get(CONF_NAME)} {account_name}"
        self._attr_icon = "mdi:bank"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._currency = account.get("balance", {}).get("currency", "NOK")
        
    @property
    def native_value(self):
        """Return the account balance."""
        if not self.coordinator.data:
            return None
        
        accounts = self.coordinator.data.get("accounts", [])
        if self.account_index >= len(accounts):
            return None
            
        account = accounts[self.account_index]
        balance = account.get("balance") or {}
        amount_str = balance.get("amount")
        # JSON always returns amounts as *strings* – convert to float so HA can store
        try:
            return float(amount_str) if amount_str is not None else None
        except (ValueError, TypeError):
            return None
    
    @property
    def native_unit_of_measurement(self):
        """Return the fixed currency unit."""
        return self._currency
    
    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        if not self.coordinator.data:
            return {}
        
        accounts = self.coordinator.data.get("accounts", [])
        if self.account_index >= len(accounts):
            return {}
            
        account = accounts[self.account_index]
        
        attributes = {
            "account_number": account.get("accountNumber", "Unknown"),
            "account_name": account.get("name", "Unknown"),
            "account_type": account.get("description", "Unknown"),
            "integration_id": self.entry.entry_id,
        }
        
        return attributes