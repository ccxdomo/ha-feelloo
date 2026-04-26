"""Constants for the Feelloo integration."""

from datetime import timedelta

DOMAIN = "feelloo"

# Firebase Auth
FIREBASE_API_KEY = "AIzaSyDuAHqBZTwfri9qC0rhayRv_7VdQCTF8co"
FIREBASE_SIGNIN_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
FIREBASE_REFRESH_URL = "https://securetoken.googleapis.com/v1/token"

# Feelloo API
BASE_URL = "https://linxmain.feelloo.com"

# Config entry keys
CONF_EMAIL = "email"
CONF_PASSWORD = "password"

# Polling intervals
CATS_UPDATE_INTERVAL = timedelta(minutes=5)
ACTIVITY_UPDATE_INTERVAL = timedelta(minutes=15)
TERRITORY_UPDATE_INTERVAL = timedelta(minutes=15)
TOKEN_REFRESH_INTERVAL = timedelta(minutes=50)

# API endpoints
ENDPOINT_CATS = "/users/cats"
ENDPOINT_ACTIVITY = "/users/cats/{cat_id}/activity"
ENDPOINT_TERRITORY_PATHS = "/users/cats/{cat_id}/territory/paths"
ENDPOINT_TERRITORY_PATH = "/users/cats/{cat_id}/territory/paths/{session_id}"
ENDPOINT_TERRITORY = "/users/cats/{cat_id}/territory"
ENDPOINT_RING = "/users/cats/{cat_id}/ring/bell-button"
