"""The Sparebank1 Pengerobot integration."""
import logging
import voluptuous as vol
from decimal import Decimal

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers import config_validation as cv
from homeassistant.exceptions import HomeAssistantError
from homeassistant.const import CONF_NAME, Platform
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectOptionDict
from homeassistant.helpers import device_registry, entity_registry


from .const import (
    DOMAIN,
    SERVICE_TRANSFER_DEBIT,
    SERVICE_TRANSFER_CREDITCARD,
    ATTR_AMOUNT,
    ATTR_FROM_ACCOUNT,
    ATTR_TO_ACCOUNT,
    ATTR_MESSAGE,
    ATTR_DUE_DATE,
    ATTR_DEVICE_ID,
    ATTR_CURRENCY_CODE,

    EVENT_MONEY_TRANSFERRED,
    DEFAULT_CURRENCY,
    CONF_DEFAULT_CURRENCY,
    CONF_MAX_AMOUNT,
    DEFAULT_MAX_AMOUNT,
    SUPPORTED_CURRENCIES,
    __version__,
    INTEGRATION_NAME,
    MANUFACTURER,
)
from .utils import (
    validate_norwegian_account_number,
    validate_amount,
    validate_amount_with_currency_conversion,
)
from .coordinator import Sparebank1Coordinator
from .api import Sparebank1APIError

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]
# OAuth2 integrations don't need YAML config support
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Custom validators for service schema
def validate_account_number(account_number: str) -> str:
    """Validate Norwegian account number."""
    if not validate_norwegian_account_number(account_number):
        raise vol.Invalid("Invalid Norwegian account number (must be 11 digits with valid checksum)")
    return account_number

def validate_amount_service(amount_str: str) -> str:
    """Validate amount for service call (will be validated with max_amount later)."""
    # Basic validation without max_amount check (will be done in service handler)
    is_valid, _, error_msg = validate_amount(amount_str)
    if not is_valid:
        raise vol.Invalid(error_msg)
    return amount_str

def get_integration_selector(hass: HomeAssistant) -> SelectSelector:
    """Create a selector for available integrations."""
    available_integrations = [
        (entry_id, data) for entry_id, data in hass.data.get(DOMAIN, {}).items()
        if isinstance(data, dict) and "coordinator" in data
    ]
    
    if not available_integrations:
        # Fallback if no integrations available yet
        options = [SelectOptionDict(value="", label="No integrations available")]
    else:
        options = [
            SelectOptionDict(
                value=entry_id,
                label=f"{data['config'].get(CONF_NAME, f'Integration {entry_id}')} ({data['config'].get(CONF_DEFAULT_CURRENCY, DEFAULT_CURRENCY)})"
            )
            for entry_id, data in available_integrations
        ]
    
    return SelectSelector(SelectSelectorConfig(options=options))

def get_currency_selector(hass: HomeAssistant, default_currency: str = DEFAULT_CURRENCY) -> SelectSelector:
    """Create a selector for supported currencies."""
    options = [
        SelectOptionDict(value=currency, label=currency)
        for currency in SUPPORTED_CURRENCIES
    ]
    
    return SelectSelector(SelectSelectorConfig(options=options))

def get_transfer_debit_schema(hass: HomeAssistant) -> vol.Schema:
    """Get the service schema with device and entity selectors."""
    return vol.Schema(
        {
            vol.Required(ATTR_DEVICE_ID): cv.string,  # Device selector
            vol.Required(ATTR_FROM_ACCOUNT): cv.entity_id,  # Entity selector
            vol.Required(ATTR_TO_ACCOUNT): cv.entity_id,  # Entity selector
            vol.Required(ATTR_AMOUNT): validate_amount_service,
            vol.Optional(ATTR_CURRENCY_CODE): get_currency_selector(hass),
            vol.Optional(ATTR_MESSAGE, default=""): cv.string,
            vol.Optional(ATTR_DUE_DATE): cv.date,
        }
    )

def get_transfer_creditcard_schema(hass: HomeAssistant) -> vol.Schema:
    """Get the service schema with device and entity selectors for credit card transfers."""
    return vol.Schema(
        {
            vol.Required(ATTR_DEVICE_ID): cv.string,  # Device selector
            vol.Required(ATTR_FROM_ACCOUNT): cv.entity_id,  # Entity selector
            vol.Required(ATTR_TO_ACCOUNT): cv.entity_id,  # Entity selector (credit card account)
            vol.Required(ATTR_AMOUNT): validate_amount_service,
            vol.Optional(ATTR_DUE_DATE): cv.date,
        }
    )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Sparebank1 Pengerobot component."""
    hass.data[DOMAIN] = {}
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Sparebank1 Pengerobot from a config entry."""
    coordinator = Sparebank1Coordinator(hass, entry)
    
    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()
    
    # Store coordinator
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "config": {
            CONF_NAME: entry.data.get(CONF_NAME),
            CONF_MAX_AMOUNT: entry.options.get(CONF_MAX_AMOUNT, entry.data.get(CONF_MAX_AMOUNT, DEFAULT_MAX_AMOUNT)),
            CONF_DEFAULT_CURRENCY: entry.options.get(CONF_DEFAULT_CURRENCY, entry.data.get(CONF_DEFAULT_CURRENCY, DEFAULT_CURRENCY)),
        }
    }
    
    # Register the transfer money service
    async def async_handle_transfer_debit(call: ServiceCall):
        """Handle the transfer money service call."""
        device_id = call.data[ATTR_DEVICE_ID]
        from_account_entity = call.data[ATTR_FROM_ACCOUNT]
        to_account_entity = call.data[ATTR_TO_ACCOUNT]
        amount_str = call.data[ATTR_AMOUNT]

        message = call.data.get(ATTR_MESSAGE, "")
        due_date = call.data.get(ATTR_DUE_DATE)
        if due_date:
            due_date = due_date.isoformat()  # Convert date object to YYYY-MM-DD string
        currency_code = call.data.get(ATTR_CURRENCY_CODE)

        # Find the coordinator based on device_id
        coordinator = None
        coordinator_data = None
        entry_id = None
        
        # Find the entry_id that corresponds to this device_id
        dev_reg = device_registry.async_get(hass)
        device = dev_reg.async_get(device_id)
        
        if not device:
            raise HomeAssistantError(f"Device {device_id} not found")
        
        # Extract entry_id from device identifiers
        for identifier in device.identifiers:
            if identifier[0] == DOMAIN:
                entry_id = identifier[1]
                break
        
        if not entry_id:
            raise HomeAssistantError(f"No integration entry found for device {device_id}")
        
        # Get coordinator for this entry
        if entry_id in hass.data[DOMAIN]:
            coordinator_data = hass.data[DOMAIN][entry_id]
            coordinator = coordinator_data.get("coordinator")
        
        if not coordinator:
            raise HomeAssistantError(f"No coordinator found for device {device_id}")
        
        # Extract account numbers from entity_ids and validate they belong to the device
        ent_reg = entity_registry.async_get(hass)
        
        from_entity = ent_reg.async_get(from_account_entity)
        to_entity = ent_reg.async_get(to_account_entity)
        
        if not from_entity or not to_entity:
            raise HomeAssistantError("Selected account entities not found")
        
        # Validate entities belong to the same device
        if from_entity.device_id != device_id or to_entity.device_id != device_id:
            raise HomeAssistantError("Selected accounts must belong to the selected device")
        
        # Validate accounts are different
        if from_account_entity == to_account_entity:
            raise HomeAssistantError("From account and to account must be different")
        
        # Extract account numbers from entity states
        from_account_state = hass.states.get(from_account_entity)
        to_account_state = hass.states.get(to_account_entity)
        
        if not from_account_state or not to_account_state:
            raise HomeAssistantError("Could not get account information")
        
        from_account = from_account_state.attributes.get("account_number")
        to_account = to_account_state.attributes.get("account_number")
        
        if not from_account or not to_account:
            raise HomeAssistantError("Could not extract account numbers from selected entities")
        
        # Determine currency: use provided currency_code, or fall back to account currency, or instance default
        instance_default_currency = coordinator_data["config"].get(CONF_DEFAULT_CURRENCY, DEFAULT_CURRENCY)
        
        if currency_code:
            # Use explicitly provided currency code
            currency = currency_code
        else:
            # Fall back to account currency or instance default
            currency = instance_default_currency
            if coordinator and coordinator.data and "accounts" in coordinator.data:
                accounts = coordinator.data["accounts"]
                for acc in accounts:
                    if acc["accountNumber"] == from_account:
                        currency = acc.get("currencyCode", instance_default_currency)
                        break

        # Validate amount with currency conversion against device limits
        max_amount = coordinator_data["config"].get(CONF_MAX_AMOUNT, DEFAULT_MAX_AMOUNT)
        device_default_currency = coordinator_data["config"].get(CONF_DEFAULT_CURRENCY, DEFAULT_CURRENCY)
        
        is_valid, amount_decimal, error_msg = validate_amount_with_currency_conversion(
            amount_str, 
            currency, 
            device_default_currency, 
            max_amount
        )
        
        if not is_valid:
            raise HomeAssistantError(f"Invalid amount: {error_msg}")
        
        # Use the validated Decimal directly to avoid double parsing
        try:
            # Perform the transfer
            result = await coordinator.async_transfer_money(
                from_account=from_account,
                to_account=to_account,
                amount=amount_decimal,
                currency=currency,
                description=message,
                due_date=due_date
            )
            
            # Fire success event
            event_data = {
                "integration_id": coordinator.entry.entry_id,
                "name": coordinator.entry.data.get(CONF_NAME),
                "currency": currency,
                "amount": float(amount_decimal),  # Use the validated Decimal amount
                "from_account": from_account,
                "to_account": to_account,
                "description": message,
                "success": True,
                "result": result,
            }
            
            # Add warnings and paymentId from API response if present
            if isinstance(result, dict):
                if "warnings" in result:
                    event_data["warnings"] = result["warnings"]
                if "paymentId" in result:
                    event_data["payment_id"] = result["paymentId"]
            
            if due_date:
                event_data["due_date"] = due_date
            
            hass.bus.async_fire(EVENT_MONEY_TRANSFERRED, event_data)
            
            _LOGGER.info(
                "Successfully transferred %s %s from %s to %s",
                amount_decimal, currency, from_account, to_account
            )
            
        except Sparebank1APIError as err:
            # Fire failure event
            event_data = {
                "integration_id": coordinator.entry.entry_id,
                "name": coordinator.entry.data.get(CONF_NAME),
                "currency": currency,
                "amount": float(amount_decimal),  # Use the validated Decimal amount
                "from_account": from_account,
                "to_account": to_account,
                "description": message,
                "success": False,
                "failure_reason": str(err),
            }
            
            # Add detailed error information if available
            if hasattr(err, 'http_code') and err.http_code:
                event_data["http_code"] = err.http_code
            if hasattr(err, 'errors') and err.errors:
                event_data["errors"] = err.errors
                event_data["error_codes"] = err.error_codes
                if err.trace_ids:
                    event_data["trace_ids"] = err.trace_ids
            
            if due_date:
                event_data["due_date"] = due_date
            
            hass.bus.async_fire(EVENT_MONEY_TRANSFERRED, event_data)
            
            _LOGGER.error("Transfer failed: %s", err)
            raise HomeAssistantError(f"Transfer failed: {err}")
        
        except Exception as err:
            # Fire failure event
            event_data = {
                "integration_id": coordinator.entry.entry_id,
                "name": coordinator.entry.data.get(CONF_NAME),
                "currency": currency,
                "amount": float(amount_decimal),  # Use the validated Decimal amount
                "from_account": from_account,
                "to_account": to_account,
                "description": message,
                "success": False,
                "failure_reason": f"Unexpected error: {err}",
            }
            
            if due_date:
                event_data["due_date"] = due_date
            
            hass.bus.async_fire(EVENT_MONEY_TRANSFERRED, event_data)
            
            _LOGGER.error("Unexpected error during transfer: %s", err)
            raise HomeAssistantError(f"Unexpected error: {err}")
    
    # Register the credit card transfer money service
    async def async_handle_transfer_creditcard(call: ServiceCall):
        """Handle the credit card transfer money service call."""
        device_id = call.data[ATTR_DEVICE_ID]
        from_account_entity = call.data[ATTR_FROM_ACCOUNT]
        to_account_entity = call.data[ATTR_TO_ACCOUNT]
        amount_str = call.data[ATTR_AMOUNT]

        due_date = call.data.get(ATTR_DUE_DATE)
        if due_date:
            due_date = due_date.isoformat()  # Convert date object to YYYY-MM-DD string

        # Find the coordinator based on device_id
        coordinator = None
        coordinator_data = None
        entry_id = None
        
        # Find the entry_id that corresponds to this device_id
        dev_reg = device_registry.async_get(hass)
        device = dev_reg.async_get(device_id)
        
        if not device:
            raise HomeAssistantError(f"Device {device_id} not found")
        
        # Extract entry_id from device identifiers
        for identifier in device.identifiers:
            if identifier[0] == DOMAIN:
                entry_id = identifier[1]
                break
        
        if not entry_id:
            raise HomeAssistantError(f"No integration entry found for device {device_id}")
        
        # Get coordinator for this entry
        if entry_id in hass.data[DOMAIN]:
            coordinator_data = hass.data[DOMAIN][entry_id]
            coordinator = coordinator_data.get("coordinator")
        
        if not coordinator:
            raise HomeAssistantError(f"No coordinator found for device {device_id}")
        
        # Extract account numbers from entity_ids and validate they belong to the device
        ent_reg = entity_registry.async_get(hass)
        
        from_entity = ent_reg.async_get(from_account_entity)
        to_entity = ent_reg.async_get(to_account_entity)
        
        if not from_entity or not to_entity:
            raise HomeAssistantError("Selected account entities not found")
        
        # Validate entities belong to the same device
        if from_entity.device_id != device_id or to_entity.device_id != device_id:
            raise HomeAssistantError("Selected accounts must belong to the selected device")
        
        # Validate accounts are different
        if from_account_entity == to_account_entity:
            raise HomeAssistantError("From account and to account must be different")
        
        # Extract account numbers from entity states
        from_account_state = hass.states.get(from_account_entity)
        to_account_state = hass.states.get(to_account_entity)
        
        if not from_account_state or not to_account_state:
            raise HomeAssistantError("Could not get account information")
        
        from_account = from_account_state.attributes.get("account_number")
        
        # Extract creditCardAccountId from the to_account entity (this is the credit card account)
        # Only use credit_card_account_id attribute - no fallbacks to other fields
        credit_card_account_id = to_account_state.attributes.get("credit_card_account_id")
        
        _LOGGER.debug(
            "Credit card transfer - from_account: %s, to_account_entity: %s, credit_card_account_id: %s (from attributes: %s)",
            from_account,
            to_account_entity,
            credit_card_account_id,
            {
                "credit_card_account_id": to_account_state.attributes.get("credit_card_account_id"),
                "account_number": to_account_state.attributes.get("account_number"),
                "account_name": to_account_state.attributes.get("account_name"),
                "all_attributes": dict(to_account_state.attributes)
            }
        )
        
        if not from_account:
            raise HomeAssistantError("Could not extract account number from selected from account entity")
        
        if not credit_card_account_id:
            # Try to get it directly from coordinator data as fallback
            if coordinator and coordinator.data and "accounts" in coordinator.data:
                accounts = coordinator.data["accounts"]
                to_account_number = to_account_state.attributes.get("account_number")
                for acc in accounts:
                    if acc.get("accountNumber") == to_account_number:
                        credit_card_account_id = acc.get("creditCardAccountID")
                        if credit_card_account_id:
                            _LOGGER.debug(
                                "Found creditCardAccountID in coordinator data: %s for account %s",
                                credit_card_account_id,
                                to_account_number
                            )
                            break
            
            if not credit_card_account_id:
                raise HomeAssistantError(
                    f"Could not extract credit card account ID from selected credit card account entity. "
                    f"Entity: {to_account_entity}, Attributes: {dict(to_account_state.attributes)}. "
                    f"The selected account must have a 'credit_card_account_id' attribute (from creditCardAccountID field). "
                    f"Make sure you selected a credit card account."
                )

        # Validate amount against device limits (credit card transfers don't use currency conversion)
        max_amount = coordinator_data["config"].get(CONF_MAX_AMOUNT, DEFAULT_MAX_AMOUNT)
        device_default_currency = coordinator_data["config"].get(CONF_DEFAULT_CURRENCY, DEFAULT_CURRENCY)
        
        is_valid, amount_decimal, error_msg = validate_amount_with_currency_conversion(
            amount_str, 
            device_default_currency,  # Credit card transfers use device default currency
            device_default_currency, 
            max_amount
        )
        
        if not is_valid:
            raise HomeAssistantError(f"Invalid amount: {error_msg}")
        
        # Use the validated Decimal directly to avoid double parsing
        try:
            # Perform the credit card transfer
            result = await coordinator.async_transfer_money_creditcard(
                from_account=from_account,
                credit_card_account_id=credit_card_account_id,
                amount=amount_decimal,
                due_date=due_date
            )
            
            # Fire success event
            event_data = {
                "integration_id": coordinator.entry.entry_id,
                "name": coordinator.entry.data.get(CONF_NAME),
                "amount": float(amount_decimal),  # Use the validated Decimal amount
                "from_account": from_account,
                "credit_card_account_id": credit_card_account_id,
                "success": True,
                "result": result,
            }
            
            # Add warnings and paymentId from API response if present
            if isinstance(result, dict):
                if "warnings" in result:
                    event_data["warnings"] = result["warnings"]
                if "paymentId" in result:
                    event_data["payment_id"] = result["paymentId"]
            
            if due_date:
                event_data["due_date"] = due_date
            
            hass.bus.async_fire(EVENT_MONEY_TRANSFERRED, event_data)
            
            _LOGGER.info(
                "Successfully transferred %s from %s to credit card account %s",
                amount_decimal, from_account, credit_card_account_id
            )
            
        except Sparebank1APIError as err:
            # Fire failure event
            event_data = {
                "integration_id": coordinator.entry.entry_id,
                "name": coordinator.entry.data.get(CONF_NAME),
                "amount": float(amount_decimal),  # Use the validated Decimal amount
                "from_account": from_account,
                "credit_card_account_id": credit_card_account_id,
                "success": False,
                "failure_reason": str(err),
            }
            
            # Add detailed error information if available
            if hasattr(err, 'http_code') and err.http_code:
                event_data["http_code"] = err.http_code
            if hasattr(err, 'errors') and err.errors:
                event_data["errors"] = err.errors
                event_data["error_codes"] = err.error_codes
                if err.trace_ids:
                    event_data["trace_ids"] = err.trace_ids
            
            if due_date:
                event_data["due_date"] = due_date
            
            hass.bus.async_fire(EVENT_MONEY_TRANSFERRED, event_data)
            
            _LOGGER.error("Credit card transfer failed: %s", err)
            raise HomeAssistantError(f"Credit card transfer failed: {err}")
        
        except Exception as err:
            # Fire failure event
            event_data = {
                "integration_id": coordinator.entry.entry_id,
                "name": coordinator.entry.data.get(CONF_NAME),
                "amount": float(amount_decimal),  # Use the validated Decimal amount
                "from_account": from_account,
                "credit_card_account_id": credit_card_account_id,
                "success": False,
                "failure_reason": f"Unexpected error: {err}",
            }
            
            if due_date:
                event_data["due_date"] = due_date
            
            hass.bus.async_fire(EVENT_MONEY_TRANSFERRED, event_data)
            
            _LOGGER.error("Unexpected error during credit card transfer: %s", err)
            raise HomeAssistantError(f"Unexpected error: {err}")
    
    # Register service if it's not already registered
    if not hass.services.has_service(DOMAIN, SERVICE_TRANSFER_DEBIT):
        hass.services.async_register(
            DOMAIN,
            SERVICE_TRANSFER_DEBIT,
            async_handle_transfer_debit,
            schema=get_transfer_debit_schema(hass),
        )
    
    # Register credit card transfer service if it's not already registered
    if not hass.services.has_service(DOMAIN, SERVICE_TRANSFER_CREDITCARD):
        hass.services.async_register(
            DOMAIN,
            SERVICE_TRANSFER_CREDITCARD,
            async_handle_transfer_creditcard,
            schema=get_transfer_creditcard_schema(hass),
        )
    
    # Create update listener
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    
    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update without reloading the entire integration."""

    # Normally, one would do this:
    #       await hass.config_entries.async_reload(entry.entry_id)
    # but in the Pengerobot case, this causes the _accounts sensor to go unavailable on
    # refreshing data and changing the number of accounts to follow, so instead we do this:

    try:
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            coordinator_data = hass.data[DOMAIN][entry.entry_id]
            coordinator: Sparebank1Coordinator | None = coordinator_data.get("coordinator")

            # Update stored config snapshot from current options/data
            updated_config = {
                CONF_NAME: entry.data.get(CONF_NAME),
                CONF_MAX_AMOUNT: entry.options.get(CONF_MAX_AMOUNT, entry.data.get(CONF_MAX_AMOUNT, DEFAULT_MAX_AMOUNT)),
                CONF_DEFAULT_CURRENCY: entry.options.get(CONF_DEFAULT_CURRENCY, entry.data.get(CONF_DEFAULT_CURRENCY, DEFAULT_CURRENCY)),
            }
            coordinator_data["config"] = updated_config
            _LOGGER.debug(
                "Options updated for entry_id=%s; new config=%s",
                entry.entry_id,
                updated_config,
            )

            # Request a data refresh to apply any selection changes
            if coordinator:
                await coordinator.async_request_refresh()
    except Exception as err:
        _LOGGER.error("Error handling options update for entry_id=%s: %s", entry.entry_id, err)    

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload sensor platform
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        # Shutdown coordinator to cancel any lingering tasks
        if entry.entry_id in hass.data[DOMAIN]:
            coordinator_data = hass.data[DOMAIN][entry.entry_id]
            if "coordinator" in coordinator_data:
                coordinator = coordinator_data["coordinator"]
                # DataUpdateCoordinator does not have async_shutdown(); use async_stop() if available
                if hasattr(coordinator, "async_stop"):
                    coordinator.async_stop()
            hass.data[DOMAIN].pop(entry.entry_id)
        
        # Check if this is the last instance of the integration
        remaining_entries = [
            k for k, v in hass.data[DOMAIN].items()
            if isinstance(v, dict) and "coordinator" in v
        ]
        
        if not remaining_entries:
            # Unregister service if this is the last instance
            if hass.services.has_service(DOMAIN, SERVICE_TRANSFER_DEBIT):
                hass.services.async_remove(DOMAIN, SERVICE_TRANSFER_DEBIT)
            if hass.services.has_service(DOMAIN, SERVICE_TRANSFER_CREDITCARD):
                hass.services.async_remove(DOMAIN, SERVICE_TRANSFER_CREDITCARD)
    
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)