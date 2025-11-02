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
            # Use same logic as sensor initialization to determine account identifier
            acc_number = acc.get("accountNumber") or acc.get("creditCardAccountID") or acc.get("accountId") or acc.get("AccountId") or f"account_{idx}"
            uniq = f"{DOMAIN}_{entry.entry_id}_account_{acc_number}"
            if uniq in added_accounts:
                continue
            try:
                new_entities.append(Sparebank1AccountBalanceSensor(coordinator, entry, acc, idx))
                added_accounts.add(uniq)
            except Exception as err:
                _LOGGER.error(
                    "Failed to create sensor for account %d (accountNumber: %s, accountId: %s, AccountId: %s): %s",
                    idx,
                    acc.get("accountNumber"),
                    acc.get("accountId"),
                    acc.get("AccountId"),
                    err,
                    exc_info=True
                )
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
        
        # Get account number - credit cards have accountNumber but it might be invalid for balance endpoint
        # Credit card format: 'K1879940508' (starts with 'K')
        self.account_number = account.get("accountNumber")
        if not self.account_number:
            # Fallback to creditCardAccountID if accountNumber is missing
            self.account_number = account.get("creditCardAccountID") or account.get("accountId") or account.get("AccountId") or f"account_{account_index}"
            _LOGGER.debug(
                "Account %d has no accountNumber. Using fallback: %s. Account keys: %s",
                account_index,
                self.account_number,
                list(account.keys()) if isinstance(account, dict) else "NOT_A_DICT"
            )
        
        account_number = self.account_number
        account_name = account.get("name", f"Account {account_index + 1}")
        
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_account_{account_number}"
        self._attr_name = f"{entry.data.get(CONF_NAME)} {account_name}"
        self._attr_icon = "mdi:bank"
        self._attr_device_class = SensorDeviceClass.MONETARY
        
        # Handle balance - API returns balance as float in accounts response for credit cards
        # For other accounts, balance might be fetched separately and stored as dict
        # Use currencyCode from account (always present)
        self._currency = account.get("currencyCode", "NOK")
        
        # Check if balance already exists in account data (from API response)
        balance = account.get("balance")
        if balance is None:
            # Balance will be set later when fetched
            _LOGGER.debug(
                "Account %s has no balance data yet. Type: %s. Balance will be fetched or set later.",
                account_number,
                account.get("type", "UNKNOWN")
            )
        
    @property
    def available(self):
        """Return False if this account no longer exists or has no balance data (mark sensor unavailable)."""
        # If coordinator has no data, fall back to base availability (handles staleness)
        if self.coordinator.data is None:
            return False
        accounts = self.coordinator.data.get("accounts", [])
        # If the specific account number is no longer present, make entity unavailable
        # Check accountNumber, creditCardAccountID, accountId, or AccountId
        account = None
        for acc in accounts:
            if (acc.get("accountNumber") == self.account_number or
                acc.get("creditCardAccountID") == self.account_number or
                acc.get("accountId") == self.account_number or
                acc.get("AccountId") == self.account_number):
                account = acc
                break
                
        if not account:
            _LOGGER.debug(
                "Account %s no longer exists in coordinator data. Available accounts: %s",
                self.account_number,
                [(acc.get("accountNumber"), acc.get("creditCardAccountID"), acc.get("accountId"), acc.get("AccountId")) for acc in accounts]
            )
            return False
            
        # For sensors, we need balance data to be available
        # If account exists but has no balance (e.g., credit card that failed balance fetch), mark unavailable
        balance = account.get("balance")
        if not balance or not isinstance(balance, dict) or "amount" not in balance:
            _LOGGER.debug(
                "Account %s exists but has no valid balance data. Balance: %s (type: %s). Marking sensor unavailable.",
                self.account_number,
                balance,
                type(balance)
            )
            return False
            
        return super().available

    @property
    def native_value(self):
        """Return the account balance."""
        if not self.coordinator.data:
            return None
        
        # Find the matching account by its stable account number, creditCardAccountID, accountId, or AccountId
        accounts = self.coordinator.data.get("accounts", [])
        # Find account by accountNumber, creditCardAccountID, accountId, or AccountId
        account = None
        for acc in accounts:
            if (acc.get("accountNumber") == self.account_number or
                acc.get("creditCardAccountID") == self.account_number or
                acc.get("accountId") == self.account_number or
                acc.get("AccountId") == self.account_number):
                account = acc
                break
                
        if not account:
            _LOGGER.debug(
                "Account %s not found when getting balance. Available accounts: accountNumbers=%s, creditCardAccountIDs=%s, accountIds=%s, AccountIds=%s",
                self.account_number,
                [acc.get("accountNumber") for acc in accounts],
                [acc.get("creditCardAccountID") for acc in accounts],
                [acc.get("accountId") for acc in accounts],
                [acc.get("AccountId") for acc in accounts]
            )
            return None
            
        balance = account.get("balance")
        if not balance:
            _LOGGER.debug(
                "Account %s has no balance data. Account keys: %s, Account: %s",
                self.account_number,
                list(account.keys()) if isinstance(account, dict) else "NOT_A_DICT",
                account
            )
            return None
            
        amount_str = balance.get("amount")
        # JSON always returns amounts as *strings* – convert to float so HA can store
        try:
            return float(amount_str) if amount_str is not None else None
        except (ValueError, TypeError) as e:
            _LOGGER.warning(
                "Could not convert balance amount to float for account %s. amount_str: %s, type: %s, error: %s",
                self.account_number,
                amount_str,
                type(amount_str),
                e
            )
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
        # Find account by accountNumber, accountId, or AccountId (for credit cards)
        account = None
        for acc in accounts:
            if (acc.get("accountNumber") == self.account_number or
                acc.get("accountId") == self.account_number or
                acc.get("AccountId") == self.account_number):
                account = acc
                break
                
        if not account:
            _LOGGER.debug(
                "Account %s not found in coordinator data. Available accounts: accountNumbers=%s, creditCardAccountIDs=%s, accountIds=%s, AccountIds=%s",
                self.account_number,
                [acc.get("accountNumber") for acc in accounts],
                [acc.get("creditCardAccountID") for acc in accounts],
                [acc.get("accountId") for acc in accounts],
                [acc.get("AccountId") for acc in accounts]
            )
            return {}
        
        # Debug: Log account structure to help debug credit card account issues
        _LOGGER.debug(
            "Building attributes for account %s. Account keys: %s, has balance: %s, has accountId: %s, has AccountId: %s",
            self.account_number,
            list(account.keys()) if isinstance(account, dict) else "NOT_A_DICT",
            "balance" in account,
            "accountId" in account,
            "AccountId" in account
        )
        
        attributes = {
            "account_number": account.get("accountNumber", "Unknown"),
            "account_name": account.get("name", "Unknown"),
            "account_type": account.get("description", "Unknown"),
            "integration_id": self.entry.entry_id,
        }
        
        # Store creditCardAccountID for credit card transfers (this is the correct field name)
        # Only store creditCardAccountID - this is the only ID field we use for credit card transfers
        if "creditCardAccountID" in account:
            attributes["credit_card_account_id"] = account.get("creditCardAccountID")
            _LOGGER.debug(
                "Account %s is a credit card with creditCardAccountID: %s",
                self.account_number,
                account.get("creditCardAccountID")
            )
        
        return attributes