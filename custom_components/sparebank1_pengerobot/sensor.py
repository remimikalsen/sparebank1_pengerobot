"""Sensor platform for Sparebank1 Pengerobot."""
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import CONF_NAME
import logging

from .const import DOMAIN, INTEGRATION_NAME, MANUFACTURER
from .coordinator import Sparebank1Coordinator

_LOGGER = logging.getLogger(__name__)


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
        return self.coordinator.last_update_success


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


class Sparebank1AccountSensor(BaseSparebank1Sensor):
    """Sensor representing Sparebank1 account status."""
    
    def __init__(self, coordinator: Sparebank1Coordinator, entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_accounts"
        self._attr_name = f"{entry.data.get(CONF_NAME)} Accounts"
        self._attr_icon = "mdi:bank"
        # Account count sensor – counts should not declare state_class to keep history pure
        # (monetary sensors must not have state_class since 2024.11, and counts work fine without it).
        
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
        
        # Add account details (first 5 accounts to avoid overwhelming the state)
        for i, account in enumerate(accounts[:5]):
            prefix = f"account_{i+1}"
            attributes[f"{prefix}_number"] = account.get("accountNumber", "Unknown")
            attributes[f"{prefix}_name"] = account.get("name", "Unknown")
            attributes[f"{prefix}_type"] = account.get("description", "Unknown")
            
            # Add balance if available
            if "balance" in account:
                balance = account["balance"]
                attributes[f"{prefix}_balance"] = balance.get("amount", 0)
                attributes[f"{prefix}_currency"] = balance.get("currency", "NOK")
            
            # Add other useful info
            if "bank" in account:
                attributes[f"{prefix}_bank"] = account["bank"].get("name", "Unknown")
        
        if len(accounts) > 5:
            attributes["note"] = f"Showing first 5 of {len(accounts)} accounts"
        
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
        # Monetary entities may no longer set state_class starting 2024.11
        self._attr_device_class = SensorDeviceClass.MONETARY
        # Fixed currency to avoid dynamic unit changes
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
        # Sparebank1 returns amounts as *strings* – convert to float so HA can store
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
        
        # Add bank info if available
        if "bank" in account:
            attributes["bank_name"] = account["bank"].get("name", "Unknown")
        
        return attributes