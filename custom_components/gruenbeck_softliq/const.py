"""Constants for the Grünbeck softliQ Cloud integration."""

from __future__ import annotations

DOMAIN = "gruenbeck_softliq"

CONF_SCAN_INTERVAL = "scan_interval"

# Grünbeck blocks accounts that poll the realtime endpoints too often.
# The vendor app and the ioBroker adapter both use 360 s as the minimum.
MIN_SCAN_INTERVAL = 360
DEFAULT_SCAN_INTERVAL = 360

# How often the slow-changing endpoints are refreshed (seconds).
DEVICE_INFO_INTERVAL = 60 * 60
PARAMETERS_INTERVAL = 60 * 60
MEASUREMENTS_INTERVAL = 60 * 60
# Retry delay after the cloud answered an endpoint with no data.
EMPTY_RETRY_INTERVAL = 30 * 60

# --- Grünbeck cloud API ---
API_BASE = "https://prod-eu-gruenbeck-api.azurewebsites.net/api"
API_VERSION = "2024-05-02"

SIGNALR_NEGOTIATE_URL = (
    "https://prod-eu-gruenbeck-signalr.service.signalr.net/client/negotiate"
    "?hub=gruenbeck"
)
SIGNALR_WS_URL = (
    "wss://prod-eu-gruenbeck-signalr.service.signalr.net/client/?hub=gruenbeck"
)

# --- Azure AD B2C login (values taken from the myGrünbeck mobile app) ---
B2C_HOST = "https://gruenbeckb2c.b2clogin.com"
B2C_CLIENT_ID = "5a83cc16-ffb1-42e9-9859-9fbf07f36df8"
B2C_REDIRECT_URI = f"msal{B2C_CLIENT_ID}://auth"
B2C_SCOPE = (
    "https://gruenbeckb2c.onmicrosoft.com/iot/user_impersonation "
    "openid profile offline_access"
)
B2C_AUTHORIZE_URL = (
    f"{B2C_HOST}/a50d35c1-202f-4da7-aa87-76e51a3098c6/b2c_1a_signinup"
    "/oauth2/v2.0/authorize"
)

APP_USER_AGENT = "Gruenbeck/354 CFNetwork/1209 Darwin/20.2.0"

# Operating modes of the softliQ (parameter "pmode")
MODE_ECO = 1
MODE_COMFORT = 2
MODE_POWER = 3
MODE_INDIVIDUAL = 4

OPERATION_MODES = {
    MODE_ECO: "eco",
    MODE_COMFORT: "comfort",
    MODE_POWER: "power",
    MODE_INDIVIDUAL: "individual",
}
