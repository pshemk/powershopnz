"""PowerShop NZ constants."""

DOMAIN = "powershopnz"

CONF_ACCOUNTS = "accounts"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_ACCOUNT_ID = "account_id"
CONF_PROPERTY_ID = "property_id"
CONF_FLOW_TYPE = "flow_type"
CONF_EMAIL="conf_email"
CONF_PROPERTY_ADDRESS = "property_address"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_ENABLED_SENSORS = "enabled_sensors"
CONF_REPROCESS_DATA = "reprocess_data"
CONF_SENSORS_OPTIONS = "sensors_options"
CONF_SENSORS_GROUPS = {
    "billing_dates": True,
    "billing_period":  True,
    "rate_type": True,
    "nominal_rates": True,
    "effective_rates": True,
    "historical_usage": True,
    "historical_cost": True,
    "powerpacks": True,
}

SENSORS_GROUPS_MAP = {
    "next_billing_date": "billing_dates",
    "current_billing_period": "billing_dates",
    "billing_period":  "billing_period" ,
    "billing_days": "billing_period",
    "unit_rate_type" : "rate_type",
    "nominal_unit" : "nominal_rates",
    "daily_charge" : "nominal_rates",  
    "effective_unit": "effective_rates",
    "effective_cost_ratio": "effective_rates",
    "historical_usage": "historical_usage",
    "historical_cost": "historical_cost",
    "powerpacks": "powerpacks",
}



#Used for checking for changes in Powerpack balances and usage data availability
DEFAULT_UPDATE_INTERVAL = 30      #30
DEFAULT_API_CALL_INTERVAL = 300    #5 mins


FIREBASE_API_KEY = "AIzaSyCYCKXQhGmo7haJxAAyO_7mIPrV7jtxsK8" 
FIREBASE_SIGN_IN_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken"
FIREBASE_REFRESH_URL = "https://securetoken.googleapis.com/v1/token"

EMAIL_CONNECTOR_URL = "https://auth.powershop.nz/cf/email-connector"
OTP_VALIDATOR_URL = "https://auth.powershop.nz/cf/email-otp-authenticator"
API_URL = "https://api.powershop.nz/v1/graphql/"

