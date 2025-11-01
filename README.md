![Build Status](https://img.shields.io/github/actions/workflow/status/remimikalsen/sparebank1_pengerobot/publish.yaml)
![HACS Test](https://img.shields.io/github/actions/workflow/status/remimikalsen/sparebank1_pengerobot/hacs.yaml?label=HACS)
![Hassfest Test](https://img.shields.io/github/actions/workflow/status/remimikalsen/sparebank1_pengerobot/hassfest.yaml?label=Hassfest)
![License](https://img.shields.io/github/license/remimikalsen/sparebank1_pengerobot)
![Version](https://img.shields.io/github/tag/remimikalsen/sparebank1_pengerobot)

# Sparebank1 Pengerobot 🏦💸

A Home Assistant integration that enables secure money transfers between your own Sparebank1 accounts. It uses OAuth 2.0 and BankID for authentication and of course encrypted communication with the bank APIs.

## Features ✨

- 🔐 **Secure OAuth 2.0 Authentication** with Norwegian BankID
- 💸 **Money Transfers** between your own accounts (debit transfers)
- 💳 **Credit Card Transfers** - transfer money to credit card accounts
- 🔄 **Automatic Token Refresh** (365-day lifecycle)
- 📊 **Account Monitoring** with hourly balance updates (select accounts wisely due to 60/hour API limit)
- 🌍 **Multi-Currency Support** (NOK, EUR, USD, etc.) - *Note: Non-NOK currencies may incur additional transfer costs*
- 📅 **Scheduled Transfers** with due date support
- 🔔 **Event Notifications** for automation integration
- 📱 **Mobile Notifications** for transfer confirmations

## Prerequisites 📋

Before installing this integration, you'll need to create an OAuth client with Sparebank1:

1. Log in to the [Sparebank1 Developer Portal](https://developer.sparebank1.no/#/documentation/gettingstarted) with BankID.
2. Create a new **OAuth client**.
3. Fill in **Client name** and **Description** as you like.
4. Select **Your bank**.
5. Set **Redirect URI** to `https://my.home-assistant.io/redirect/oauth`.
6. Save and copy the generated **Client ID** and **Client Secret** – you will paste these into Home Assistant later.

> 💡 **Multiple Bank Accounts?** You can create multiple OAuth clients to connect different accounts or separate access for different purposes. See [Multiple OAuth Clients](#multiple-oauth-clients) below.

## Installation 📦

### Via HACS (Recommended)

Note! After HACS 2.0 the process is slightly different, just go straight to the three dots in the upper right corner, paste the custom repo url and choose "integration", then skip to step 7 below. 

1. Ensure you have [HACS](https://hacs.xyz/) installed in Home Assistant
2. In HACS, go to **Integrations**
3. Click the **⋮** menu → **Custom repositories**
4. Add this repository URL: `https://github.com/remimikalsen/sparebank1_pengerobot`
5. Select **Integration** as the category
6. Click **Add**
7. Find "Sparebank1 Pengerobot" in HACS list and install it / download it
8. **Restart Home Assistant**

### Manual Installation

1. Download the latest release from GitHub
2. Extract the `sparebank1_pengerobot` folder to your `custom_components` directory
3. Restart Home Assistant

## Configuration 🔧

### Step 1: Add the Integration

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for "Sparebank1 Pengerobot" and select it

### Step 2: Instance Settings

In the first screen you choose per-instance options:

- **Name** – friendly label shown in Home Assistant
- **Default Currency** – default currency to move money with (NOK set as default) - *Note: Choosing currencies other than NOK may incur additional transfer costs*
- **Maximum Amount** – maximum amount to transfer in the default currency (enforced cross-currency in-service)

Click **Next**.

### Step 3: Application Credentials Setup

**If this is your first integration instance:**
- Home Assistant will show a **Create credentials** option
- Choose a credential **Name** and paste your **Client ID** and **Client Secret**
- Click **Create** and proceed to Step 4

> ⚠️ **Important**: Opening the Application Credentials helper can be painfully slow. Just wait - and then wait a little more - and then some.

**If you already have credentials configured:**
- Select from existing credentials in the dropdown
- Or go to **Settings** → **Application Credentials** first to add more OAuth clients
- See [Multiple OAuth Clients](#multiple-oauth-clients) for detailed guidance

### Step 4: OAuth Authorization

1. Click **Authorize** to begin the OAuth flow
2. Choose your bank from the Sparebank1 list
3. Log in with BankID (your Norwegian digital ID)
4. Review and approve the requested permissions
5. Click **Link Account** when redirected to **my.home-assistant.io**
6. The authorization window closes and Home Assistant continues setup

### Step 5: Account Selection

After successful authorization, you'll be asked to select which accounts to monitor:

1. **Review Available Accounts**: The integration will show all your accessible accounts
2. **Select Strategically**: Choose only the accounts you need for automation/monitoring
3. **Consider API Limits**: Sparebank1 allows **60 API calls per hour**
   - Each monitored account uses API calls for balance updates
   - **Recommendation**: Select 2-4 most important accounts to stay well within limits
   - You can always add/remove accounts later in integration settings

4. **Save Selection**: Click **Submit** to complete setup

> ⚠️ **Important**: The integration polls account balances hourly. With 60 API calls/hour limit, monitoring too many accounts may cause rate limiting. Start with fewer accounts and add more if needed.

🎉 **Setup Complete!** Your integration will now:
- Automatically refresh tokens as needed
- Monitor your selected accounts hourly (including credit card accounts)
- Be ready to process money transfers via the `transfer_debit` and `transfer_creditcard` services

## Usage 💰

### Basic Money Transfer (Debit)

Use the `sparebank1_pengerobot.transfer_debit` service to transfer money between bank accounts:

```yaml
service: sparebank1_pengerobot.transfer_debit
data:
  device_id: "abc123def456"          # Device ID from integration
  from_account: "sensor.account_1"   # From account sensor entity ID
  to_account: "sensor.account_2"     # To account sensor entity ID  
  amount: "500.00"                   # Amount to transfer (as string)
  currency_code: "NOK"               # Currency (optional, uses default)
  message: "Rent payment"            # Transfer description (optional)
  due_date: "2024-02-15"             # Schedule for later (optional)
```

### Credit Card Transfer

Note! This function is new and untested as I don't have a credit card account at SNN, but it's completely safe to try it out as the Sparebank1 API won't allow transferring money to accounts that aren't your own.

Use the `sparebank1_pengerobot.transfer_creditcard` service to transfer money from a bank account to a credit card account:

```yaml
service: sparebank1_pengerobot.transfer_creditcard
data:
  device_id: "abc123def456"          # Device ID from integration
  from_account: "sensor.checking_account"   # From bank account sensor entity ID
  to_account: "sensor.credit_card_account"  # To credit card account sensor entity ID  
  amount: "1500.00"                   # Amount to transfer (as string)
  due_date: "2024-02-15"             # Schedule for later (optional, defaults to current date)
```

> ⚠️ **Credit Card Transfers**: 
> - Credit card transfers only support transfers TO credit card accounts (paying down credit card debt)
> - The `to_account` must be a credit card account with an `account_id` attribute
> - Currency and message fields are not supported for credit card transfers
> - The amount uses the device's default currency (no currency conversion)

> ⚠️ **Currency Costs**: Choosing currencies other than NOK may incur additional transfer costs from your bank (debit transfers only).

> 💡 **Finding Entity IDs**: Go to **Developer Tools** → **States** and search for your account sensors, or use the entity picker in the service call UI.

### In Automations - Manual Transfer

Create an automation to transfer money based on triggers:

```yaml
automation:
  - alias: "Monthly Rent Transfer"
    trigger:
      - platform: time
        at: "09:00:00"
    condition:
      - condition: template
        value_template: "{{ now().day == 1 }}"  # First day of month
    action:
      - service: sparebank1_pengerobot.transfer_debit
        data:
          device_id: "abc123def456"  # Your integration device ID
          from_account: "sensor.checking_account"
          to_account: "sensor.bills_account"
          amount: "15000"
          currency_code: "NOK"
          message: "Monthly rent - {{ now().strftime('%B %Y') }}"
```

### In Automations - Conditional Transfer  

Transfer money based on sensor values or other conditions:

```yaml
automation:
  - alias: "Surplus Savings Transfer"
    trigger:
      - platform: numeric_state
        entity_id: sensor.main_account_balance
        above: 50000  # When balance exceeds 50,000 NOK
    action:
      - service: sparebank1_pengerobot.transfer_debit
        data:
          device_id: "abc123def456"
          from_account: "sensor.main_account"
          to_account: "sensor.savings_account"
          amount: "{{ (states('sensor.main_account') | float - 45000) | round(0) }}"
          currency_code: "NOK"
          message: "Automatic savings transfer"
```

### In Automations - Credit Card Payment

Automatically pay down credit card debt:

```yaml
automation:
  - alias: "Monthly Credit Card Payment"
    trigger:
      - platform: time
        at: "08:00:00"
    condition:
      - condition: template
        value_template: "{{ now().day == 15 }}"  # 15th of each month
    action:
      - service: sparebank1_pengerobot.transfer_creditcard
        data:
          device_id: "abc123def456"
          from_account: "sensor.checking_account"
          to_account: "sensor.credit_card_account"
          amount: "{{ (states('sensor.credit_card_account') | float * -1) | round(0) }}"
          due_date: "{{ now().strftime('%Y-%m-%d') }}"
```

## Event Notifications 🔔

The integration fires `sparebank1_pengerobot_money_transferred` events after each transfer attempt. Use these for notifications and logging.

### Success Notification

```yaml
automation:
  - alias: "Transfer Success Notification"
    trigger:
      - platform: event
        event_type: sparebank1_pengerobot_money_transferred
        event_data:
          success: true
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "💸 Transfer Successful"
          message: >
            {% if trigger.event.data.credit_card_account_id %}
              {{ trigger.event.data.amount }} transferred from {{ trigger.event.data.from_account }}
              to credit card {{ trigger.event.data.credit_card_account_id }}
            {% else %}
              {{ trigger.event.data.amount }} {{ trigger.event.data.currency }}
              transferred from {{ trigger.event.data.from_account }}
              to {{ trigger.event.data.to_account }}
            {% endif %}
          data:
            priority: high
            color: green
```

### Failure Alert

```yaml
automation:
  - alias: "Transfer Failure Alert"
    trigger:
      - platform: event
        event_type: sparebank1_pengerobot_money_transferred
        event_data:
          success: false
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "❌ Transfer Failed"
          message: >
            {% if trigger.event.data.credit_card_account_id %}
              Transfer of {{ trigger.event.data.amount }} to credit card {{ trigger.event.data.credit_card_account_id }}
              failed: {{ trigger.event.data.failure_reason }}
            {% else %}
              Transfer of {{ trigger.event.data.amount }} {{ trigger.event.data.currency }}
              failed: {{ trigger.event.data.failure_reason }}
            {% endif %}
          data:
            priority: high
            color: red
      - service: persistent_notification.create
        data:
          title: "Money Transfer Failed"
          message: >
            Failed to transfer {{ trigger.event.data.amount }} {{ trigger.event.data.currency }}
            from {{ trigger.event.data.from_account }} to {{ trigger.event.data.to_account }}.
            Reason: {{ trigger.event.data.failure_reason }}
```

### Comprehensive Transfer Log

```yaml
automation:
  - alias: "Log All Transfers"
    trigger:
      - platform: event
        event_type: sparebank1_pengerobot_money_transferred
    action:
      - service: logbook.log
        data:
          name: "Sparebank1 Transfer"
          message: >
            {% if trigger.event.data.success %}
              ✅ Successfully transferred {{ trigger.event.data.amount }}
              {% if trigger.event.data.currency %}{{ trigger.event.data.currency }}{% endif %}
              from {{ trigger.event.data.from_account }}
              {% if trigger.event.data.credit_card_account_id %}
                to credit card {{ trigger.event.data.credit_card_account_id }}
              {% else %}
                to {{ trigger.event.data.to_account }}
                {% if trigger.event.data.description %}({{ trigger.event.data.description }}){% endif %}
              {% endif %}
            {% else %}
              ❌ Failed to transfer {{ trigger.event.data.amount }}
              {% if trigger.event.data.currency %}{{ trigger.event.data.currency }}{% endif %}:
              {{ trigger.event.data.failure_reason }}
            {% endif %}
```

## Event Data Structure 📋

The `sparebank1_pengerobot_money_transferred` event contains:

### Common Fields (Always Present)
```yaml
integration_id: "abc123..."        # Integration instance ID
name: "My Sparebank1 Account"     # Integration name
amount: 500.0                     # Transfer amount
from_account: "12345678901"       # Source account
success: true                     # Transfer success/failure
due_date: "2024-02-15"           # Due date (if scheduled)
result: {...}                    # Full API response data
```

### Debit Transfer Fields
```yaml
currency: "NOK"                   # Transfer currency (debit transfers only)
to_account: "10987654321"         # Destination account number (debit transfers)
description: "Rent payment"       # Transfer description/message (debit transfers only)
```

### Credit Card Transfer Fields
```yaml
credit_card_account_id: "1034222"  # Credit card account ID (credit card transfers only)
# Note: currency and description fields are not present for credit card transfers
```

### Success-Only Fields
```yaml
# Present when transfer succeeds and API returns additional data:
warnings: ["DUPLICATE_PAYMENT_EXISTS"]  # API warnings (if any)
payment_id: "12345789012"              # Transaction ID from bank
```

### Failure-Only Fields  
```yaml
# Present when transfer fails:
failure_reason: "Insufficient funds"    # Human-readable error message
http_code: 403                         # HTTP status code from API
errors: [                              # Structured error details from API
  {
    "code": "insufficient_funds",
    "message": "Account balance insufficient for transfer",
    "traceId": "trace-abc123",
    "httpCode": 403,
    "resource": "account"
  }
]
error_codes: ["insufficient_funds"]     # Extracted error codes
trace_ids: ["trace-abc123"]            # API trace IDs for support
```

## Sensors 📊

The integration provides an account sensor that shows:

- **State**: Number of connected accounts
- **Attributes**: Account details, balances, and last update time

Access account information in automations:

```yaml
# Check if main account balance is low
condition:
  - condition: template
    value_template: >
      {{ state_attr('sensor.my_sparebank1_account_accounts', 'account_1_balance') | float < 1000 }}
```

## Token Management 🔑

- **Automatic Refresh**: Tokens refresh automatically before expiration
- **365-Day Lifecycle**: Refresh tokens last up to 365 days
- **Manual Renewal**: When refresh tokens expire, you'll need to re-authorize (same process as initial setup)
- **Secure Storage**: All tokens are encrypted in Home Assistant's configuration


## Multiple OAuth Clients 🔗

This integration supports multiple OAuth clients and application credentials, enabling you to:

- Get access to bank accounts from different Sparebank1 member banks
- Separate access for different family members or purposes  
- Maintain isolated configurations with different settings for each client

### Setting Up Multiple OAuth Clients

#### Step 1: Create Additional OAuth Clients (if needed)

If you need different OAuth clients:

1. Visit the [Sparebank1 Developer Portal](https://developer.sparebank1.no/#/documentation/gettingstarted)
2. Create additional OAuth clients for each separate access you need
3. Use the same redirect URI: `https://my.home-assistant.io/redirect/oauth`
4. Note down each Client ID and Client Secret

#### Step 2: Add Application Credentials in Home Assistant

**For your first OAuth client:**
- The integration setup will guide you through credential creation
- No pre-setup required

**For additional OAuth clients:**

1. Go to **Settings** → **Devices & Services** → **Application Credentials**
2. Click **Add Application Credential** 
3. Select **Sparebank1 Pengerobot**
4. Enter a descriptive **Name** (e.g., "Sparebank1 - Personal", "Sparebank1 - Business")
5. Paste the **Client ID** and **Client Secret**
6. Click **Create**

Repeat for each additional OAuth client you want to use.

#### Step 3: Create Integration Instances

**For each OAuth client/bank account combination:**

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for and select **Sparebank1 Pengerobot**
4. Configure instance settings (Name, Currency, Max Amount)
5. **Select the appropriate Application Credential** from the dropdown
6. Complete the OAuth authorization process
7. Each instance will get its own unique device ID and sensors

### Using Multiple Instances in Services

When you have multiple integration instances, specify which one to use in your service calls:

```yaml
# Instance 1 - Personal account  (debit transfer)
service: sparebank1_pengerobot.transfer_debit
data:
  device_id: "personal_device_id"  # Device ID from personal instance
  from_account: "sensor.personal_checking"
  to_account: "sensor.personal_savings"
  amount: "1000"
  message: "Personal savings transfer"

# Instance 2 - Business account (debit transfer)
service: sparebank1_pengerobot.transfer_debit  
data:
  device_id: "business_device_id"  # Device ID from business instance
  from_account: "sensor.business_checking"
  to_account: "sensor.business_savings"
  amount: "5000"
  message: "Business expense transfer"

# Credit card transfer example
service: sparebank1_pengerobot.transfer_creditcard
data:
  device_id: "personal_device_id"
  from_account: "sensor.personal_checking"
  to_account: "sensor.personal_credit_card"
  amount: "3000"
  due_date: "2024-03-01"
```

### Finding Your Device IDs

1. Go to **Settings** → **Devices & Services**
2. Find your Sparebank1 Pengerobot integrations
3. Click on each integration to see its device
4. The device ID is shown in the device information
5. Or use **Developer Tools** → **Services** to see device options in the service call UI


### Managing Multiple Instances

**Token Renewal**: Each instance handles token renewal independently. If one instance's tokens expire, it won't affect others.

**Configuration Changes**: Update settings for each instance separately in **Settings** → **Devices & Services** → **Configure**.

**Troubleshooting**: Check logs and diagnostics for each instance separately if issues arise.

**Rate Limiting with Multiple Instances**: Each OAuth client has its own 60 API calls/hour limit (from my understanding, but I might be wrong). Be mindful of total account monitoring across all instances to avoid overwhelming your setup with API calls. The integration wil automatically back off if it enters a state where it gets HTTP 429 back from the server.

## Troubleshooting 🔧

### Common Issues

**"OAuth authorization failed"**
- Verify your Client ID and Client Secret are correct
- Ensure you copied the authorization code completely
- Try the authorization process again

**"Token expired" errors**
- The integration should auto-refresh tokens
- If persistent, remove and re-add the integration

**"Cannot connect to Sparebank1"**
- Check your internet connection
- Verify Sparebank1 API is accessible from your network

**Transfer failures**
- Ensure sufficient funds in source account
- Verify transfer limits with your bank
- Verify that the from and to accounts both are accessible by the selected client/device
- For credit card transfers: Ensure the selected `to_account` is a credit card account with an `account_id` attribute

**"Rate limit exceeded" or API errors**
- You may be monitoring too many accounts (limit: 60 API calls/hour)
- Reduce monitored accounts: **Settings** → **Devices & Services** → **Configure** your integration
- Each account polls hourly. Theoretically, you shoyld be able to follow 60 accounts, but do little more with no room to run transactions.
- Consider monitoring only accounts you use for transfers/automation

### Enable Debug Logging

Add to `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.sparebank1_pengerobot: debug
```

## Security Notes 🔒

- All authentication uses OAuth 2.0 with BankID (Norwegian national digital ID)
- The integration only accesses and transfers funds from and to your own accounts
- All API calls use HTTPS encryption
- Tokens, client_id and client_secret are stored unencrypted in Home Assistant in .storage/auth like any other application credentials managed by Home Assistant - this is the Home Assistant way! The information in the auth-file can be used by anyone to get a fresh access token and transfer money. Understand the implications of this and secure your Home Assistant server and backups.
- If the integration is used in bad faith, it could cost you money in transfer costs (currency conversions for example), but according to the Sparebank1 APIs it is not be possible to transfer money away from your own accounts.
- If you suspect a breach, the only safe step is to delete the client from the Sparebank1 developer portal - and the integration and all stored tokens will be rendered useless.

## Support 💬

- 🐛 **Issues**: [GitHub Issues](https://github.com/remimikalsen/sparebank1_pengerobot/issues)
- 📖 **Sparebank1 API**: [Developer Documentation](https://developer.sparebank1.no/)

## License 📄

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

**⚠️ Disclaimer**: This integration is not officially affiliated with Sparebank1. Use at your own risk and always verify transfers before executing them.