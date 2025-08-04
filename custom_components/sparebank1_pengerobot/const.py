"""Constants for the Sparebank1 Pengerobot integration."""

__version__ = "0.0.3"
DOMAIN = "sparebank1_pengerobot"
INTEGRATION_NAME = "Sparebank1 Pengerobot"
MANUFACTURER = "@remimikalsen (https://github.com/remimikalsen)"

# Configuration constants
CONF_DEFAULT_CURRENCY = "default_currency"
CONF_MAX_AMOUNT = "max_amount"
CONF_SELECTED_ACCOUNTS = "selected_accounts"
CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_ACCESS_TOKEN = "access_token"
CONF_TOKEN_EXPIRES_AT = "token_expires_at"
CONF_TOKEN = "token"


# Sparebank1 API endpoints
API_BASE_URL = "https://api.sparebank1.no"
OAUTH_BASE_URL = "https://api.sparebank1.no/oauth"
OAUTH_AUTHORIZE_URL = f"{OAUTH_BASE_URL}/authorize"
OAUTH_TOKEN_URL = f"{OAUTH_BASE_URL}/token"
TRANSFER_ENDPOINT = "/personal/banking/transfer/debit"

# OAuth constants
OAUTH_REDIRECT_URI = "https://my.home-assistant.io/redirect/oauth"

# Service call constants
SERVICE_TRANSFER_DEBIT = "transfer_debit"
ATTR_CURRENCY = "currency"
ATTR_AMOUNT = "amount"
ATTR_FROM_ACCOUNT = "from_account"
ATTR_TO_ACCOUNT = "to_account"
ATTR_MESSAGE = "message"
ATTR_DUE_DATE = "due_date"
ATTR_DEVICE_ID = "device_id"
ATTR_CURRENCY_CODE = "currency_code"

# Event constants
EVENT_MONEY_TRANSFERRED = "sparebank1_pengerobot_money_transferred"

# Supported currencies
SUPPORTED_CURRENCIES = ["NOK", "EUR", "USD", "SEK", "DKK", "GBP"]

# Currency exchange rates (fixed rates relative to NOK)
CURRENCY_RATES = {
    "NOK": 1.0,     # Base currency
    "SEK": 1.0,     # 1 NOK = 1 SEK
    "DKK": 1.0,     # 1 NOK = 1 DKK  
    "USD": 0.1,     # 1 USD = 10 NOK
    "EUR": 0.083,   # 1 EUR = 12 NOK (1/12 ≈ 0.083)
    "GBP": 0.071,   # 1 GBP = 14 NOK (1/14 ≈ 0.071)
}

# Default values
DEFAULT_CURRENCY = "NOK"
DEFAULT_MAX_AMOUNT = 200  # Default maximum transfer amount in NOK
TOKEN_REFRESH_THRESHOLD = 300  # Refresh token 5 minutes before expiry

# Validation constants
NORWEGIAN_ACCOUNT_NUMBER_LENGTH = 11