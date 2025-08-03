"""DataUpdateCoordinator for Sparebank1 Pengerobot."""
import logging
from datetime import timedelta, datetime
from decimal import Decimal

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_entry_oauth2_flow

from .api import Sparebank1Client, Sparebank1AuthError, Sparebank1APIError, Sparebank1RateLimitError
from .const import DOMAIN, CONF_SELECTED_ACCOUNTS

_LOGGER = logging.getLogger(__name__)


class Sparebank1Coordinator(DataUpdateCoordinator):
    """Class to manage fetching Sparebank1 data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.hass = hass
        self.oauth_session = None
        self.client = None

        # Backoff tracking for repeated authentication failures
        self._backoff_attempts: int = 0  # How many consecutive auth failures
        self._backoff_until: datetime | None = None  # Wall-clock time we can retry again
        
        # Rate limit backoff tracking
        self._rate_limit_backoff_until: datetime | None = None

        # Store the default update interval so we can restore it after a success
        self._default_update_interval = timedelta(hours=1)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=1),  # Check accounts hourly
        )

    async def _ensure_client_initialized(self) -> None:
        """Ensure OAuth session and client are initialized."""
        if self.oauth_session is not None and self.client is not None:
            return
            
        # Get OAuth2 implementation and create session
        implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
            self.hass, self.entry
        )
        self.oauth_session = config_entry_oauth2_flow.OAuth2Session(
            self.hass, self.entry, implementation
        )

        # Create the API client
        self.client = Sparebank1Client(self.hass, self.entry, self.oauth_session)

    async def _async_update_data(self):
        """Fetch data from Sparebank1."""

        # Respect any backoff window caused by repeated authentication failures
        if self._backoff_until and datetime.utcnow() < self._backoff_until:
            remaining = int((self._backoff_until - datetime.utcnow()).total_seconds())
            _LOGGER.warning(
                "Still in backoff period – %s seconds remaining before next attempt", remaining
            )
            raise UpdateFailed("Backoff in effect, will retry later")
            
        # Respect rate limit backoff
        if self._rate_limit_backoff_until and datetime.utcnow() < self._rate_limit_backoff_until:
            remaining = int((self._rate_limit_backoff_until - datetime.utcnow()).total_seconds())
            _LOGGER.warning(
                "Rate limit backoff active – %s seconds remaining before next attempt", remaining
            )
            raise UpdateFailed("Rate limited, will retry later")
        try:
            # Ensure OAuth session and client are initialized
            await self._ensure_client_initialized()
            
            # Ensure we have a valid token (refreshes automatically if needed)
            await self.oauth_session.async_ensure_token_valid()
            
            # Get account information
            accounts = await self.client.get_accounts()
            
            # Filter accounts to only include selected ones
            selected_account_numbers = self.entry.data.get(CONF_SELECTED_ACCOUNTS, [])
            if selected_account_numbers:
                accounts = [
                    acc for acc in accounts 
                    if acc.get("accountNumber") in selected_account_numbers
                ]
                _LOGGER.debug("Filtered to %d selected accounts from config", len(accounts))
            else:
                _LOGGER.debug("No account selection configured, using all %d accounts", len(accounts))

            # Attempt to enrich with balances (only for filtered accounts)
            try:
                # Build list of account numbers we have to look up
                account_numbers = [
                    acc["accountNumber"]
                    for acc in accounts
                    if "accountNumber" in acc
                ]
                
                balances = await self.client.get_account_balances(account_numbers)
                
                for acc in accounts:
                    acc_no = acc["accountNumber"]
                    if acc_no not in balances:
                        continue
                    bal_resp = balances[acc_no]
                    acc["balance"] = {
                        "amount": bal_resp["accountBalance"],
                        "currency": acc.get("currencyCode", "NOK"),
                    }
            except Exception as err:  # noqa: BLE001 – non-fatal, we just log and continue
                _LOGGER.warning("Could not fetch account balances: %s", err)
                # Sensors will fall back to 0 until next successful refresh

            # Successful fetch – reset all backoff tracking and restore default interval
            if self._backoff_attempts or self._backoff_until or self._rate_limit_backoff_until:
                _LOGGER.info("Successful fetch – resetting all backoff counters")
                self._backoff_attempts = 0
                self._backoff_until = None
                self._rate_limit_backoff_until = None
                if self.update_interval != self._default_update_interval:
                    self.update_interval = self._default_update_interval

            return {
                "accounts": accounts,
                "last_update": datetime.utcnow().isoformat(),
            }
            
        except Sparebank1AuthError as auth_err:
            _LOGGER.error("Authentication error: %s", auth_err)
            # Increment backoff attempts and calculate next retry time
            self._backoff_attempts += 1
            backoff_seconds = min(2 ** self._backoff_attempts * 60, 3600)  # cap at 1 hour
            self._backoff_until = datetime.utcnow() + timedelta(seconds=backoff_seconds)
            _LOGGER.warning("Backing off for %s seconds (next attempt at %s)", backoff_seconds, self._backoff_until.isoformat())
            raise UpdateFailed(f"Authentication failed: {auth_err}")
        except Sparebank1RateLimitError as rate_err:
            _LOGGER.error("Rate limit error: %s", rate_err)
            # Extract retry-after seconds from the error message, default to 1 hour
            try:
                import re
                match = re.search(r'Retry after (\d+) seconds', str(rate_err))
                backoff_seconds = int(match.group(1)) if match else 3600
            except (ValueError, AttributeError):
                backoff_seconds = 3600  # Default to 1 hour
            
            self._rate_limit_backoff_until = datetime.utcnow() + timedelta(seconds=backoff_seconds)
            _LOGGER.warning(
                "Rate limited - backing off for %s seconds until %s", 
                backoff_seconds, 
                self._rate_limit_backoff_until.isoformat()
            )
            raise UpdateFailed(f"Rate limited: {rate_err}")
        except Sparebank1APIError as api_err:
            _LOGGER.error("API error: %s", api_err)
            raise UpdateFailed(f"API error: {api_err}")
        except Exception as err:
            _LOGGER.error("Unexpected error: %s", err)
            raise UpdateFailed(f"Unexpected error: {err}")



    async def async_transfer_money(self, from_account: str, to_account: str, amount: Decimal | str,
                                 currency: str = "NOK", description: str = "", due_date: str = None) -> dict:
        """Transfer money between accounts."""
        try:
            # Ensure OAuth session and client are initialized
            await self._ensure_client_initialized()
            
            result = await self.client.transfer_money(
                from_account=from_account,
                to_account=to_account,
                amount=amount,
                currency=currency,
                description=description,
                due_date=due_date
            )
            
            # Trigger data refresh to get updated account balances
            await self.async_request_refresh()
            
            return result
            
        except (Sparebank1AuthError, Sparebank1APIError, Sparebank1RateLimitError) as err:
            _LOGGER.error("Transfer failed: %s", err)
            raise
        except Exception as err:
            _LOGGER.error("Unexpected error during transfer: %s", err)
            raise Sparebank1APIError(f"Unexpected error: {err}")