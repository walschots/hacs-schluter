"""Constants for the Schluter DITRA-HEAT-E-WiFi integration."""

from datetime import timedelta

DOMAIN = "schluter"

API_BASE_URL = "https://ditra-heat-e-wifi.schluter.com"
API_AUTH_URL = f"{API_BASE_URL}/api/authenticate/user"
API_THERMOSTATS_URL = f"{API_BASE_URL}/api/thermostats"
API_THERMOSTAT_URL = f"{API_BASE_URL}/api/thermostat"
API_APPLICATION_ID = 7

UPDATE_INTERVAL = timedelta(minutes=1)
REQUEST_TIMEOUT = 20

# Minimum time between two logins. Protects the account if Schluter starts
# rejecting fresh sessions straight away, so we never hammer the login API.
MIN_LOGIN_INTERVAL = timedelta(minutes=5)

# Regulation modes used by the Schluter cloud.
REGULATION_MODE_SCHEDULE = 1
REGULATION_MODE_MANUAL = 3

PRESET_SCHEDULE = "schedule"
PRESET_MANUAL = "manual"
