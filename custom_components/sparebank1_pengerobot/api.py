"""
API functions for Sparebank1 Pengerobot
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from decimal import Decimal

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import HomeAssistantError

from .const import API_BASE_URL, TRANSFER_ENDPOINT

_LOGGER = logging.getLogger(__name__)


class Sparebank1APIError(HomeAssistantError):
    """Exception raised when the REST API returns an error."""
    
    def __init__(self, message: str, errors: list = None, http_code: int = None):
        super().__init__(message)
        self.errors = errors or []
        self.http_code = http_code
    
    @property
    def error_codes(self) -> list[str]:
        """Get list of error codes from structured errors."""
        return [error.get("code", "") for error in self.errors if isinstance(error, dict)]
    
    @property 
    def trace_ids(self) -> list[str]:
        """Get list of trace IDs from structured errors."""
        return [error.get("traceId", "") for error in self.errors if isinstance(error, dict) and error.get("traceId")]


class Sparebank1RateLimitError(Sparebank1APIError):
    """Exception raised when the API returns a 429 rate limit error."""


class Sparebank1Client:  # pragma: no cover – thin wrapper
    """Tiny async client for the Sparebank1 personal-banking API."""

    def __init__(self, hass, oauth_session) -> None:
        self.hass = hass
        self.oauth_session = oauth_session
        self.session = async_get_clientsession(hass)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _auth_headers(self) -> Dict[str, str]:
        """Return fully-populated authorization + gateway headers."""
        
        await self.oauth_session.async_ensure_token_valid()
        access_token = self.oauth_session.token["access_token"]

        return {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.sparebank1.v1+json; charset=utf-8",
        }

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        """Generic HTTP request helper with error handling."""

        headers = await self._auth_headers()

        # Merge caller-supplied headers if any
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))
        kwargs["headers"] = headers

        try:
            async with self.session.request(method, url, **kwargs) as resp:
                if resp.status >= 400:
                    # Try to parse structured error response first
                    structured_errors = []
                    error_text = ""
                    
                    try:
                        error_json = await resp.json()
                        if isinstance(error_json, dict) and "errors" in error_json:
                            structured_errors = error_json["errors"]
                        # Convert JSON back to text for fallback error message
                        import json
                        error_text = json.dumps(error_json)
                    except Exception:
                        # If JSON parsing fails, get raw text
                        try:
                            error_text = await resp.text()
                        except Exception:
                            error_text = "Unable to read error response"
                    
                    # Check for rate limit error (429)
                    if resp.status == 429:
                        retry_after = resp.headers.get("Retry-After", "3600")  # Default to 1 hour
                        raise Sparebank1RateLimitError(
                            f"Rate limit exceeded. Retry after {retry_after} seconds: {error_text}",
                            errors=structured_errors,
                            http_code=resp.status
                        )
                    
                    # Create descriptive error message
                    if structured_errors:
                        # Build error message from structured errors
                        error_messages = []
                        for error in structured_errors:
                            if isinstance(error, dict):
                                code = error.get("code", "unknown")
                                message = error.get("message", "No message provided")
                                error_messages.append(f"{code}: {message}")
                        error_message = f"{method} {url} failed – HTTP {resp.status}: {'; '.join(error_messages)}"
                    else:
                        error_message = f"{method} {url} failed – HTTP {resp.status}: {error_text}"
                    
                    raise Sparebank1APIError(
                        error_message,
                        errors=structured_errors,
                        http_code=resp.status
                    )
                return await resp.json()
        except aiohttp.ClientError as exc:
            _LOGGER.error("Network error talking to Sparebank1: %s", exc)
            raise Sparebank1APIError(f"Network error: {exc}") from exc

    # ------------------------------------------------------------------
    # Public API methods the coordinator / integration uses
    # ------------------------------------------------------------------
    async def get_accounts(self) -> Any:
        """Return a list of the user’s bank accounts."""
        url = f"{API_BASE_URL}/personal/banking/accounts"

        params = {
            "includeNokAccounts": "true",
            "includeCurrencyAccounts": "true",
            "includeBsuAccounts": "true",
            "includeCreditCardAccounts": "false",
            "includeAskAccounts": "false",
            "includePensionAccounts": "false"
        }

        response = await self._request("GET", url, params=params)

        _LOGGER.debug("Response from get_accounts: %s", response)

        return response["accounts"]
    
    async def get_account_balances(self, account_numbers: list[str]) -> dict[str, Any]:
        """Return balances for the provided account numbers.
        
        The Sparebank1 gateway expects a POST for every account number:
            POST /personal/banking/accounts/balance
            { "accountNumber": "12345678903" }
        
        We therefore loop through the supplied list and build a mapping
        {accountNumber: balance_response}.
        """
        results: dict[str, Any] = {}
        url = f"{API_BASE_URL}/personal/banking/accounts/balance"

        # Content-Type header is mandatory for this endpoint
        content_type_header = {
            "Content-Type": "application/vnd.sparebank1.v1+json; charset=utf-8",
        }          
        
        for acc_no in account_numbers:
            payload = {"accountNumber": acc_no}
            try:
                resp = await self._request("POST", url, json=payload, headers=content_type_header)
                results[acc_no] = resp
            except Sparebank1APIError as err:
                _LOGGER.error("Could not fetch balance for %s: %s", acc_no, err)
        return results

    async def transfer_money(
        self,
        from_account: str,
        to_account: str,
        amount: Decimal | str,
        currency: str = "NOK",
        description: str = "",
        due_date: str | None = None,
    ) -> Any:
        """Initiate a domestic transfer."""
        url = f"{API_BASE_URL}{TRANSFER_ENDPOINT}"
        
        # API expects amount as a *decimal string* with two decimals (e.g. "1234.56").
        from decimal import Decimal, ROUND_HALF_UP
        amount_decimal = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        amount_str = format(amount_decimal, "f")
        
        payload: Dict[str, Any] = {
            "amount": amount_str,
            "fromAccount": from_account,
            "toAccount": to_account,
            "currencyCode": currency,
        }
        if description:
            payload["message"] = description
        if due_date:
            # The API accepts YYYY-MM-DD directly
            payload["dueDate"] = due_date

        # Content-Type header is mandatory for this endpoint
        content_type_header = {
            "Content-Type": "application/vnd.sparebank1.v1+json; charset=utf-8",
        }            

        return await self._request("POST", url, json=payload, headers=content_type_header)
