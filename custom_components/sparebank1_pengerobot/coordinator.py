"""DataUpdateCoordinator for Sparebank1 Pengerobot."""
import logging
from datetime import timedelta, datetime
from decimal import Decimal

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_entry_oauth2_flow

from .api import Sparebank1Client, Sparebank1APIError, Sparebank1RateLimitError
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
        self.client = Sparebank1Client(self.hass, self.oauth_session)

    async def _async_update_data(self):
        """Fetch data from Sparebank1."""
            
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
            
            # Get account information
            accounts = await self.client.get_accounts()
            
            # Debug: Log full account structure for each account to understand credit card account format
            _LOGGER.debug("Raw accounts from API (count: %d):", len(accounts))
            for idx, acc in enumerate(accounts):
                _LOGGER.debug(
                    "Account %d structure: keys=%s, accountNumber=%s, accountId=%s, AccountId=%s, name=%s, description=%s",
                    idx,
                    list(acc.keys()) if isinstance(acc, dict) else "NOT_A_DICT",
                    acc.get("accountNumber", "MISSING"),
                    acc.get("accountId", "MISSING"),
                    acc.get("AccountId", "MISSING"),
                    acc.get("name", "MISSING"),
                    acc.get("description", "MISSING"),
                )
            
            # Filter accounts to only include selected ones
            # Check options first (from options flow), then fall back to data (from initial config)
            selected_account_numbers = self.entry.options.get(CONF_SELECTED_ACCOUNTS, self.entry.data.get(CONF_SELECTED_ACCOUNTS, []))
            _LOGGER.debug("Selected account numbers from config: %s", selected_account_numbers)
            
            if selected_account_numbers:
                filtered_accounts = []
                for acc in accounts:
                    acc_no = acc.get("accountNumber")
                    if acc_no in selected_account_numbers:
                        filtered_accounts.append(acc)
                    else:
                        _LOGGER.debug(
                            "Account filtered out - accountNumber: %s, name: %s",
                            acc_no,
                            acc.get("name", "Unknown")
                        )
                accounts = filtered_accounts
                _LOGGER.debug("Filtered to %d selected accounts from config", len(accounts))
            else:
                _LOGGER.debug("No account selection configured, using all %d accounts", len(accounts))

            # Attempt to enrich with balances (only for filtered accounts)
            # This is truly non-fatal - we can still provide account info without balances
            balance_fetch_errors = []
            try:
                # Build list of account numbers we have to look up
                # Only include accounts that have accountNumber (credit cards might not support balance endpoint)
                account_numbers = []
                accounts_without_accountnumber = []
                
                for acc in accounts:
                    acc_no = acc.get("accountNumber")
                    acc_type = acc.get("type", "")
                    
                    # Skip credit cards - they have balance already in response and accountNumber starts with 'K' (invalid for balance endpoint)
                    if acc_type == "CREDITCARD" or (acc_no and acc_no.startswith("K")):
                        accounts_without_accountnumber.append({
                            "name": acc.get("name", "Unknown"),
                            "type": acc_type,
                            "accountNumber": acc_no,
                            "reason": "Credit card - balance already in response or invalid accountNumber"
                        })
                        _LOGGER.debug(
                            "Skipping balance fetch for credit card account - name: %s, accountNumber: %s, type: %s",
                            acc.get("name", "Unknown"),
                            acc_no,
                            acc_type
                        )
                        continue
                    
                    if acc_no:
                        account_numbers.append(acc_no)
                    else:
                        accounts_without_accountnumber.append({
                            "name": acc.get("name", "Unknown"),
                            "keys": list(acc.keys()) if isinstance(acc, dict) else "NOT_A_DICT"
                        })
                        _LOGGER.debug(
                            "Skipping balance fetch for account without accountNumber - name: %s, keys: %s",
                            acc.get("name", "Unknown"),
                            list(acc.keys()) if isinstance(acc, dict) else "NOT_A_DICT"
                        )
                
                if accounts_without_accountnumber:
                    _LOGGER.warning(
                        "Found %d account(s) without accountNumber field - these may be credit card accounts that don't support balance endpoint: %s",
                        len(accounts_without_accountnumber),
                        accounts_without_accountnumber
                    )
                
                # First, handle accounts that already have balance in the response (like credit cards)
                # Credit cards have balance as a float directly in the response
                for acc in accounts:
                    acc_no = acc.get("accountNumber")
                    acc_type = acc.get("type", "")
                    
                    # Check if account already has balance data (credit cards have it directly)
                    if "balance" in acc and isinstance(acc.get("balance"), (int, float)):
                        balance_float = acc.get("balance")
                        available_balance = acc.get("availableBalance", balance_float)
                        
                        # Convert to our internal format
                        acc["balance"] = {
                            "amount": str(balance_float),  # Store as string like API does
                            "currency": acc.get("currencyCode", "NOK"),
                        }
                        _LOGGER.debug(
                            "Account %s (type: %s) already has balance data in response: %s %s",
                            acc_no,
                            acc_type,
                            balance_float,
                            acc.get("currencyCode", "NOK")
                        )
                        
                        # Remove from account_numbers list if it was there (don't fetch again)
                        if acc_no in account_numbers:
                            account_numbers.remove(acc_no)
                            _LOGGER.debug("Skipping balance fetch for account %s - already has balance data", acc_no)
                
                # Now fetch balances for accounts that don't have it yet
                if account_numbers:
                    _LOGGER.debug("Attempting to fetch balances for %d accounts: %s", len(account_numbers), account_numbers)
                    balances = await self.client.get_account_balances(account_numbers)
                    _LOGGER.debug("Balance fetch completed - got balances for %d accounts", len(balances))
                    
                    for acc in accounts:
                        acc_no = acc.get("accountNumber")
                        if not acc_no or acc_no not in account_numbers:
                            # Skip accounts without accountNumber or already processed
                            continue
                            
                        if acc_no not in balances:
                            _LOGGER.debug(
                                "No balance data returned for account %s (name: %s) - balance endpoint may not support this account type",
                                acc_no,
                                acc.get("name", "Unknown")
                            )
                            continue
                            
                        bal_resp = balances[acc_no]
                        _LOGGER.debug(
                            "Balance response for account %s: %s",
                            acc_no,
                            bal_resp
                        )
                        
                        # Check if accountBalance exists in response
                        if "accountBalance" in bal_resp:
                            acc["balance"] = {
                                "amount": bal_resp["accountBalance"],
                                "currency": acc.get("currencyCode", "NOK"),
                            }
                        else:
                            _LOGGER.warning(
                                "Balance response for account %s missing 'accountBalance' field. Response keys: %s, Response: %s",
                                acc_no,
                                list(bal_resp.keys()) if isinstance(bal_resp, dict) else "NOT_A_DICT",
                                bal_resp
                            )
                else:
                    _LOGGER.warning("No accounts with accountNumber found - cannot fetch any balances")
            except Exception as err:  # noqa: BLE001 – non-fatal, we just log and continue
                balance_fetch_errors.append(str(err))
                _LOGGER.warning("Could not fetch account balances: %s", err, exc_info=True)
                # Continue with account data without balances - this should not fail the entire update

            # Successful fetch – reset all backoff tracking and restore default interval
            if self._rate_limit_backoff_until:
                _LOGGER.info("Successful fetch – resetting all backoff counters")
                self._rate_limit_backoff_until = None
                if self.update_interval != self._default_update_interval:
                    self.update_interval = self._default_update_interval

            data = {
                "accounts": accounts,
                "last_update": datetime.utcnow().isoformat(),
            }
            
            # Include balance fetch errors if any occurred
            if balance_fetch_errors:
                data["balance_fetch_errors"] = balance_fetch_errors
                data["balance_fetch_partial"] = True
            else:
                data["balance_fetch_partial"] = False
                
            return data
            
        except Sparebank1RateLimitError as rate_err:
            _LOGGER.error("Rate limit error: %s", rate_err)
            # Extract retry-after seconds from the error message, default to 1 hour
            try:
                import re
                # TODO Not sure if the API gives hints about this - something to reverse engineer later
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
            
            # Refresh only the affected account balances
            try:
                await self.async_refresh_account_balances([from_account, to_account])
            except Exception as _partial_err:  # Fallback to full refresh on any issue
                _LOGGER.debug("Partial balance refresh failed, falling back to full refresh: %s", _partial_err)
                await self.async_request_refresh()
            
            return result
            
        except (Sparebank1APIError, Sparebank1RateLimitError) as err:
            _LOGGER.error("Transfer failed: %s", err)
            raise
        except Exception as err:
            _LOGGER.error("Unexpected error during transfer: %s", err)
            raise Sparebank1APIError(f"Unexpected error: {err}")

    async def async_transfer_money_creditcard(self, from_account: str, credit_card_account_id: str, amount: Decimal | str,
                                             due_date: str = None) -> dict:
        """Transfer money to a credit card account using credit card transfer."""
        try:
            # Ensure OAuth session and client are initialized
            await self._ensure_client_initialized()
            
            result = await self.client.transfer_money_creditcard(
                from_account=from_account,
                credit_card_account_id=credit_card_account_id,
                amount=amount,
                due_date=due_date
            )
            
            # Refresh only the affected account balances (from account)
            try:
                await self.async_refresh_account_balances([from_account])
            except Exception as _partial_err:  # Fallback to full refresh on any issue
                _LOGGER.debug("Partial balance refresh failed, falling back to full refresh: %s", _partial_err)
                await self.async_request_refresh()
            
            return result
            
        except (Sparebank1APIError, Sparebank1RateLimitError) as err:
            _LOGGER.error("Credit card transfer failed: %s", err)
            raise
        except Exception as err:
            _LOGGER.error("Unexpected error during credit card transfer: %s", err)
            raise Sparebank1APIError(f"Unexpected error: {err}")

    async def async_refresh_account_balances(self, account_numbers: list[str]) -> None:
        """Refresh balances only for specified account numbers and update coordinator data.

        Falls back to a no-op if coordinator has no existing account list.
        """
        if not account_numbers:
            return
        # Ensure client
        await self._ensure_client_initialized()
        
        # If we don't have a current dataset, a partial update doesn't make sense
        if not self.data or "accounts" not in self.data:
            # Nothing to merge into – do a full refresh instead
            await self.async_request_refresh()
            return
        
        try:
            balances = await self.client.get_account_balances(account_numbers)
        except Exception as err:
            # Surface error to caller to decide fallback
            raise err
        
        updated_any = False
        accounts = self.data.get("accounts", [])
        for acc in accounts:
            acc_no = acc.get("accountNumber")
            if acc_no in balances:
                bal_resp = balances[acc_no]
                acc["balance"] = {
                    "amount": bal_resp.get("accountBalance"),
                    "currency": acc.get("currencyCode", acc.get("balance", {}).get("currency", "NOK")),
                }
                updated_any = True
        
        if updated_any:
            # Update the timestamp and notify listeners
            self.data["last_update"] = datetime.utcnow().isoformat()
            # Mark that only a subset was refreshed
            self.data["balance_fetch_partial"] = True
            self.async_set_updated_data(self.data)