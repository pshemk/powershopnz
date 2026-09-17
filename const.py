"""PowerShop NZ constants."""

DOMAIN = "powershopnz"

CONF_ACCOUNTS = "accounts"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_ACCOUNT_ID = "account_id"
CONF_PROPERTY_ID = "property_id"
CONF_FLOW_TYPE = "flow_type"
CONF_REGION = "region"
CONF_PLAN = "plan"
CONF_NETWORK_COMPANY = "network_company"
CONF_USER_ID = "user_id"
CONF_EMAIL="conf_email"
CONF_ACCOUNT_ID = "account_id"
CONF_PROPERTY_ID = "property_id"
CONF_PROPERTY_ADDRESS = "property_address"
CONF_PROPERTY_NAME = "property_name"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_RATES_SCHEDULE = "rates_schedule"


#Used for checking for changes in Powerpack balances and usage data availability
DEFAULT_UPDATE_INTERVAL = 60       #1 min
DEFAULT_API_CALL_INTERVAL = 300    #5 mins


FIREBASE_API_KEY = "AIzaSyCYCKXQhGmo7haJxAAyO_7mIPrV7jtxsK8" 
FIREBASE_SIGN_IN_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken"
FIREBASE_REFRESH_URL = "https://securetoken.googleapis.com/v1/token"

EMAIL_CONNECTOR_URL = "https://auth.powershop.nz/cf/email-connector"
OTP_VALIDATOR_URL = "https://auth.powershop.nz/cf/email-otp-authenticator"
API_URL = "https://api.powershop.nz/v1/graphql/"
BRAND = "powershop"
BRAND_UC = "POWERSHOP"
