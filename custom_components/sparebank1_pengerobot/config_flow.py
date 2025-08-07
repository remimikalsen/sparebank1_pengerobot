"""Config flow for Sparebank1 Pengerobot integration using Home-Assistant's built-in
OAuth2 helpers.  
The flow keeps the extra per-instance settings (friendly name, default
currency, max transfer amount) while delegating the whole OAuth dance to the
Application-Credentials system.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.config_entry_oauth2_flow import (
    AbstractOAuth2FlowHandler, async_get_implementations
)
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectOptionDict

from homeassistant.helpers import config_entry_oauth2_flow
from .api import Sparebank1Client

from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.const import CONF_NAME
from homeassistant.helpers.translation import async_get_translations

from .const import (
    DOMAIN,
    CONF_DEFAULT_CURRENCY,
    CONF_MAX_AMOUNT,
    CONF_SELECTED_ACCOUNTS,
    DEFAULT_CURRENCY,
    DEFAULT_MAX_AMOUNT,
    SUPPORTED_CURRENCIES,
)

_LOGGER = logging.getLogger(__name__)


@config_entries.HANDLERS.register(DOMAIN)
class Sparebank1OAuth2FlowHandler(AbstractOAuth2FlowHandler):
    """Handle the OAuth2 config flow for Sparebank1."""

    DOMAIN = DOMAIN
    VERSION = 1  # reverted back to original version

    # Sentinel used in the forced picker to branch into "create new credentials"
    PSEUDO_CREATE_NEW = "__create_new__"

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return _LOGGER

    def __init__(self) -> None:
        super().__init__()
        # Store user-supplied data (name / currency / max_amount) between steps
        self._user_data: Dict[str, Any] = {}
        # Store OAuth2 data until we get integration config
        self._oauth_data: Dict[str, Any] = {}
        # Store fetched accounts for selection step
        self._available_accounts: list = []

    # ---------------------------------------------------------------------
    # OAuth2 flow - let parent handle application credentials first
    # ---------------------------------------------------------------------
    async def async_step_user(
        self, user_input: Dict[str, Any] | None = None
    ) -> FlowResult:  # noqa: D401 – Home-Assistant signature
        """Start OAuth2 flow - force picking (or creating) an Application Credential."""
        return await self.async_step_pick_implementation_forced()

    def _impl_label(self, impl) -> str:
        """Create a readable, disambiguated label for an Application Credential."""

        # Append a short client_id suffix to distinguish multiple entries
        client_id = getattr(impl, "client_id", None)
        if isinstance(client_id, str) and len(client_id) >= 6:
            name = f"Client ID ({client_id[:6]}...)"
        return name

    async def async_step_pick_implementation_forced(
        self, user_input: Dict[str, Any] | None = None
    ) -> FlowResult:
        """Show implementation picker with different behavior based on existing credentials."""
        implementations = await async_get_implementations(self.hass, DOMAIN)

        if user_input is None:
            # Build readable choices for each existing credential
            choices = {
                impl_domain: self._impl_label(impl)
                for impl_domain, impl in implementations.items()
            }
            
            # Different behavior based on whether credentials exist
            if not implementations:
                # No credentials exist - show integrated flow with "create new" option
                translations = await async_get_translations(
                    self.hass, self.hass.config.language, "config", DOMAIN
                )
                create_new_text = translations.get(
                    "config.step.pick_implementation_forced.data.create_new_credentials",
                    "➕ Create new credentials…"
                )
                choices[self.PSEUDO_CREATE_NEW] = create_new_text
                
                # Use description for no credentials case
                step_id = "pick_implementation_forced"
                description_placeholders = {"count": "0"}
            else:
                # Credentials exist - only show existing ones
                # Use different step_id to get different description text
                step_id = "pick_implementation_existing"
                description_placeholders = {"count": str(len(implementations))}

            schema = vol.Schema({vol.Required("impl"): vol.In(choices)})
            return self.async_show_form(
                step_id=step_id,
                data_schema=schema,
                description_placeholders=description_placeholders
            )

        picked = user_input["impl"]

        if picked == self.PSEUDO_CREATE_NEW:
            # User chose to create new credentials (only available when no implementations exist)
            # Use the integrated flow
            _LOGGER.debug("User chose to create new credentials - using integrated flow")
            return await super().async_step_pick_implementation()
        
        if not implementations:
            # This shouldn't happen, but just in case
            return self.async_abort(reason="no_application_credentials")

        # Use the explicitly chosen implementation and continue with OAuth
        # Delegate to parent's pick_implementation with the selected implementation
        # This ensures proper initialization of flow_impl
        _LOGGER.debug("User chose existing implementation: %s", picked)
        _LOGGER.debug("Available implementations: %s", list(implementations.keys()))
        return await super().async_step_pick_implementation({"implementation": picked})

    async def async_step_pick_implementation_existing(
        self, user_input: Dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the existing credentials selection step - delegates to the main handler."""
        # This step is just for showing different UI text, the logic is the same
        return await self.async_step_pick_implementation_forced(user_input)

    # ---------------------------------------------------------------------
    # Step to gather per-instance parameters after OAuth2 setup
    # ---------------------------------------------------------------------
    async def async_step_integration_config(
        self, user_input: Dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for name, default currency and spending limit."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._user_data = user_input
            # Now we have OAuth2 data and integration config, proceed to account selection
            return await self.async_step_account_selection()

        # Get localized default name using translations
        translations = await async_get_translations(
            self.hass, self.hass.config.language, "config", DOMAIN
        )
        default_name = translations.get(
            "config.step.integration_config.data.default_integration_name", 
            "My accounts"  # fallback
        )

        # Create currency selector
        currency_options = [
            SelectOptionDict(value=currency, label=currency)
            for currency in SUPPORTED_CURRENCIES
        ]
        currency_selector = SelectSelector(SelectSelectorConfig(options=currency_options))
        
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_NAME, default=default_name
                ): str,
                vol.Optional(
                    CONF_DEFAULT_CURRENCY, default=DEFAULT_CURRENCY
                ): currency_selector,
                vol.Optional(
                    CONF_MAX_AMOUNT, default=DEFAULT_MAX_AMOUNT
                ): vol.Coerce(int),
            }
        )
        return self.async_show_form(step_id="integration_config", data_schema=schema, errors=errors)

    # ---------------------------------------------------------------------
    # Step to select which accounts to track
    # ---------------------------------------------------------------------
    async def async_step_account_selection(
        self, user_input: Dict[str, Any] | None = None
    ) -> FlowResult:
        """Allow user to select which accounts to track."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_accounts = user_input.get(CONF_SELECTED_ACCOUNTS, [])
            if not selected_accounts:
                errors[CONF_SELECTED_ACCOUNTS] = "at_least_one_account"
            else:
                # Store selected accounts and create entry
                self._user_data[CONF_SELECTED_ACCOUNTS] = selected_accounts
                return await self.async_oauth_create_entry(self._oauth_data)

        # Fetch available accounts using the API client
        try:
            # Get the auth implementation domain from OAuth data
            auth_impl_domain = self._oauth_data.get("auth_implementation")
            if not auth_impl_domain:
                _LOGGER.error("No auth implementation found in OAuth data")
                return self.async_abort(reason="accounts_fetch_failed")
            
            # Get the implementation using the domain
            implementations = await async_get_implementations(self.hass, DOMAIN)
            implementation = implementations.get(auth_impl_domain)
            if not implementation:
                _LOGGER.error("Could not find implementation for domain: %s", auth_impl_domain)
                return self.async_abort(reason="accounts_fetch_failed")
            
            # Create a minimal mock entry for the OAuth session
            from types import SimpleNamespace
            mock_entry = SimpleNamespace()
            # Put the token in the entry data where OAuth2Session expects it
            token_data = self._oauth_data.get("token", self._oauth_data)
            mock_entry.data = {
                "auth_implementation": auth_impl_domain,
                "token": token_data
            }
            mock_entry.entry_id = "temp_config_flow"
            mock_entry.domain = DOMAIN
            
            # Create OAuth session using the found implementation
            oauth_session = config_entry_oauth2_flow.OAuth2Session(self.hass, mock_entry, implementation)
            
            client = Sparebank1Client(self.hass, oauth_session)
            self._available_accounts = await client.get_accounts()
            
            if not self._available_accounts:
                return self.async_abort(reason="no_accounts_found")
        except Exception as err:
            _LOGGER.error("Failed to fetch accounts for selection: %s", err)
            return self.async_abort(reason="accounts_fetch_failed")

        # Create account selection options
        account_options = []
        for account in self._available_accounts:
            account_number = account.get("accountNumber", "")
            account_name = account.get("name", "")
            account_type = account.get("description", "")
            
            # Create a descriptive label
            label_parts = []
            if account_name:
                label_parts.append(account_name)
            if account_type:
                label_parts.append(f"({account_type})")
            if account_number:
                label_parts.append(f"- {account_number}")
            
            label = " ".join(label_parts) if label_parts else account_number
            
            account_options.append(SelectOptionDict(
                value=account_number,
                label=label
            ))

        if not account_options:
            return self.async_abort(reason="no_accounts_found")

        # Create multiselect for accounts
        account_selector = SelectSelector(SelectSelectorConfig(
            options=account_options,
            multiple=True
        ))

        schema = vol.Schema({
            vol.Required(CONF_SELECTED_ACCOUNTS): account_selector,
        })

        return self.async_show_form(
            step_id="account_selection", 
            data_schema=schema, 
            errors=errors,
            description_placeholders={
                "account_count": str(len(account_options))
            }
        )





    # ---------------------------------------------------------------------
    # Helper – fetch a stable unique ID for the account after OAuth succeeds
    # ---------------------------------------------------------------------
    async def _determine_unique_id(self, token_data: Dict[str, Any], auth_impl: str) -> str | None:  # noqa: C901
        """Return a unique ID based on the first account number; returns None on failure."""
        try:
            # Use the API client to fetch accounts for unique ID determination
            auth_impl_domain = token_data.get("auth_implementation")
            if not auth_impl_domain:
                _LOGGER.debug("No auth implementation found in token data for unique ID determination")
                return None
            
            # Get the implementation using the domain
            implementations = await async_get_implementations(self.hass, DOMAIN)
            implementation = implementations.get(auth_impl_domain)
            if not implementation:
                _LOGGER.debug("Could not find implementation for domain: %s", auth_impl_domain)
                return None
                
            from types import SimpleNamespace
            mock_entry = SimpleNamespace()
            # Put the token in the entry data where OAuth2Session expects it
            token_dict = token_data.get("token", token_data)
            mock_entry.data = {
                "auth_implementation": auth_impl_domain,
                "token": token_dict
            }
            mock_entry.entry_id = "temp_unique_id_determination"
            mock_entry.domain = DOMAIN
            
            # Use the found implementation
            oauth_session = config_entry_oauth2_flow.OAuth2Session(self.hass, mock_entry, implementation)
            
            client = Sparebank1Client(self.hass, oauth_session)
            accounts = await client.get_accounts()
            
            if isinstance(accounts, list) and accounts:
                account_number = accounts[0].get("accountNumber")
                return str(account_number) if account_number else None

        except Exception as err:  # broad – fallback to no unique_id
            _LOGGER.debug("Could not determine unique ID: %s", err)
            return None

        return None

    # ---------------------------------------------------------------------
    # Called automatically after OAuth completes and a token is obtained
    # ---------------------------------------------------------------------
    async def async_oauth_create_entry(self, data: Dict[str, Any]) -> FlowResult:
        """Create or update the config-entry once Home Assistant has the token."""
        
        # Check if this is called from account_selection step (has user config) or OAuth completion (no user config yet)
        if not self._user_data:
            # This is the first call after OAuth - store OAuth data and collect integration config
            self._oauth_data = data
            _LOGGER.debug("OAuth2 token received, now collecting integration config")
            return await self.async_step_integration_config()
        
        # This is the final call with integration config and selected accounts - now create the entry
        _LOGGER.debug("Creating entry with OAuth2 token, integration config, and selected accounts – incoming keys: %s", list(data.keys()))

        # Try to figure out a stable unique ID (customer or account identifier)
        unique_id: str | None = await self._determine_unique_id(data, data.get("auth_implementation"))

        # Fallback 1 – use OAuth "sub" claim if present
        if not unique_id:
            unique_id = str(data.get("sub")) if data.get("sub") else None

        # If we still do not have a unique ID we abort – the integration cannot
        # be set up without one in HA 2025+
        if not unique_id:
            return self.async_abort(reason="cannot_determine_unique_id")

        # -----------------------------------------------------------------
        # Scope the unique_id to the chosen Application Credential so that
        # different credentials can create separate config entries.
        # -----------------------------------------------------------------
        auth_impl = data.get("auth_implementation")
        if not auth_impl and hasattr(self, "implementation") and self.implementation:
            auth_impl = self.implementation.domain
        if not auth_impl:
            return self.async_abort(reason="missing_auth_implementation")

        base_uid = str(unique_id)
        scoped_uid = f"{base_uid}::{auth_impl}" if auth_impl else base_uid
        
        _LOGGER.debug("Creating entry with base_uid=%s, auth_impl=%s, scoped_uid=%s", base_uid, auth_impl, scoped_uid)

        # Always use the scoped unique ID
        await self.async_set_unique_id(scoped_uid)
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch()
        elif self.source == SOURCE_RECONFIGURE:
            self._abort_if_unique_id_mismatch()
        else:
            # For new setups, check if this exact scoped unique ID is already configured
            # If it is, that means the user is trying to set up the same credentials again
            existing_entry = None
            for entry in self._async_current_entries():
                if entry.unique_id == scoped_uid:
                    existing_entry = entry
                    break
            
            if existing_entry:
                _LOGGER.debug("Entry with scoped unique ID %s already exists: %s", scoped_uid, existing_entry.title)
                # This specific combination of bank account and OAuth credentials already exists
                return self.async_abort(
                    reason="already_configured",
                    description_placeholders={
                        "name": existing_entry.title,
                        "auth_impl": auth_impl
                    }
                )
            
            # No conflict with the scoped unique ID, we can create the entry
            _LOGGER.debug("No existing entry found with scoped unique ID %s, proceeding with creation", scoped_uid)

        # -----------------------------------------------------------------
        # Build entry_data following HA OAuth2 conventions:
        #   entry.data["token"]  -> full token dict
        #   entry.data["auth_implementation"] -> implementation domain
        # plus our instance-specific settings from self._user_data
        # -----------------------------------------------------------------
        # TODO: This is a hack to get the token dict and auth_implementation from the data
        if "token" in data:
            _LOGGER.debug("Token found in data 1: %s", data["token"])
            token_dict = data["token"]
            auth_impl = data.get("auth_implementation")
        else:
            # Older HA versions / the generic handler sometimes provide the
            # raw token dict at the top level. Detect that and wrap it.
            token_keys = {"access_token", "refresh_token", "expires_in", "expires_at"}
            if token_keys.intersection(data.keys()):
                _LOGGER.debug("Token keys found in data 2: %s", token_keys.intersection(data.keys()))
                token_dict = {k: v for k, v in data.items() if k in token_keys or k == "token_type"}
                auth_impl = data.get("auth_implementation")
            else:
                _LOGGER.debug("Token keys not found in data 3: %s", data.keys())
                token_dict = {}
                auth_impl = data.get("auth_implementation")

        if not auth_impl and hasattr(self, "implementation") and self.implementation:
            _LOGGER.debug("WAIT!!! Auth implementation found in self.implementation: %s", self.implementation)
            auth_impl = self.implementation.domain

        entry_data = {
            **self._user_data,
            "token": token_dict,
            "auth_implementation": auth_impl,
        }
        _LOGGER.debug("Prepared entry_data with token keys: %s and auth_impl: %s", list(token_dict.keys()), auth_impl)
        # Use a simple title
        title = "Sparebank1"

        # Handle reauthentication – update existing entry instead of creating a new one
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(),
                data_updates=entry_data,
            )

        # Handle reconfiguration – update existing entry instead of creating a new one
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                data_updates=entry_data,
            )

        return self.async_create_entry(title=title, data=entry_data)

    # ---------------------------------------------------------------------
    # Reauthentication support
    # ---------------------------------------------------------------------
    async def async_step_reauth(self, entry_data: Dict[str, Any]) -> FlowResult:
        """Initiate a reauthentication flow."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: Dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask the user to confirm they really want to reauthenticate."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm", data_schema=vol.Schema({}))
        return await self.async_step_user()

    # ---------------------------------------------------------------------
    # Reconfiguration support (change credentials and account selection)
    # ---------------------------------------------------------------------
    async def async_step_reconfigure(self, user_input: Dict[str, Any] | None = None) -> FlowResult:
        """Handle a reconfiguration flow initiated by the user."""
        return await self.async_step_reconfigure_confirm()

    async def async_step_reconfigure_confirm(
        self, user_input: Dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask the user to confirm they want to reconfigure."""
        if user_input is None:
            return self.async_show_form(
                step_id="reconfigure_confirm", 
                data_schema=vol.Schema({}),
                description_placeholders={
                    "title": self._get_reconfigure_entry().title
                }
            )
        return await self.async_step_user()

    # ---------------------------------------------------------------------
    # Expose an options flow so the user can change settings later
    # ---------------------------------------------------------------------
    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return Sparebank1OptionsFlow()


class Sparebank1OptionsFlow(config_entries.OptionsFlow):
    """Handle the options UI (change currency, max amount, and selected accounts)."""

    def __init__(self) -> None:
        super().__init__()
        self._available_accounts: list = []

    async def async_step_init(self, user_input: Dict[str, Any] | None = None) -> FlowResult:  # noqa: D401
        """Handle the initial options step."""
        if user_input is not None:
            # Check if account selection changed to determine if we need to reload
            current_accounts = self.config_entry.options.get(CONF_SELECTED_ACCOUNTS, self.config_entry.data.get(CONF_SELECTED_ACCOUNTS, []))
            new_accounts = user_input.get(CONF_SELECTED_ACCOUNTS, current_accounts)
            
            # If account selection changed, we need to reload the integration to create/remove sensors
            accounts_changed = set(current_accounts) != set(new_accounts)
            
            if accounts_changed:
                _LOGGER.debug("Account selection changed from %s to %s, will trigger reload", current_accounts, new_accounts)
            
            # Create the options entry (this will trigger the update listener which reloads the integration)
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        data = self.config_entry.data

        # Create currency selector for options flow
        currency_options = [
            SelectOptionDict(value=currency, label=currency)
            for currency in SUPPORTED_CURRENCIES
        ]
        currency_selector = SelectSelector(SelectSelectorConfig(options=currency_options))

        # Try to fetch current accounts for selection
        account_selector = None
        try:
            # Use the same approach as the config flow but with the existing config entry
            implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(self.hass, self.config_entry)
            oauth_session = config_entry_oauth2_flow.OAuth2Session(self.hass, self.config_entry, implementation)
            
            client = Sparebank1Client(self.hass, oauth_session)
            self._available_accounts = await client.get_accounts()
            
            if self._available_accounts:
                account_options = []
                for account in self._available_accounts:
                    account_number = account.get("accountNumber", "")
                    account_name = account.get("name", "")
                    account_type = account.get("description", "")
                    
                    # Create a descriptive label
                    label_parts = []
                    if account_name:
                        label_parts.append(account_name)
                    if account_type:
                        label_parts.append(f"({account_type})")
                    if account_number:
                        label_parts.append(f"- {account_number}")
                    
                    label = " ".join(label_parts) if label_parts else account_number
                    
                    account_options.append(SelectOptionDict(
                        value=account_number,
                        label=label
                    ))
                
                account_selector = SelectSelector(SelectSelectorConfig(
                    options=account_options,
                    multiple=True
                ))
        except Exception as err:
            _LOGGER.warning("Could not fetch accounts for options: %s", err)

        schema_fields = {
            vol.Optional(
                CONF_DEFAULT_CURRENCY,
                default=options.get(
                    CONF_DEFAULT_CURRENCY,
                    data.get(CONF_DEFAULT_CURRENCY, DEFAULT_CURRENCY),
                ),
            ): currency_selector,
            vol.Optional(
                CONF_MAX_AMOUNT,
                default=options.get(
                    CONF_MAX_AMOUNT, data.get(CONF_MAX_AMOUNT, DEFAULT_MAX_AMOUNT)
                ),
            ): vol.Coerce(int),
        }

        # Add account selector if available
        if account_selector:
            current_selected = options.get(
                CONF_SELECTED_ACCOUNTS,
                data.get(CONF_SELECTED_ACCOUNTS, [])
            )
            schema_fields[vol.Optional(
                CONF_SELECTED_ACCOUNTS,
                default=current_selected
            )] = account_selector

        schema = vol.Schema(schema_fields)
        return self.async_show_form(step_id="init", data_schema=schema)



    @staticmethod
    async def async_migrate_entry(hass, config_entry):
        """Migrate old config entries to newer versions."""
        version = config_entry.version

        _LOGGER.debug("Migrating config entry from version %s", version)

        # Future migration from version 1 to 2
        # if version == 1:
        #     # Add any data changes needed here
        #     _LOGGER.info("Migrating config entry from version 1 to 2")
        #     config_entry.version = 2
        #     hass.config_entries.async_update_entry(config_entry)
        #     version = 2

        # Future migration from version 2 to 3
        # if version == 2:
        #     # Add any data changes needed here
        #     _LOGGER.info("Migrating config entry from version 2 to 3")
        #     config_entry.version = 3
        #     hass.config_entries.async_update_entry(config_entry)

        _LOGGER.info("Config entry already at latest version %s", config_entry.version)
        return True
