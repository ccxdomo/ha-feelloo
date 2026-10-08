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

# Polling control (Spec 047)
CONF_POLLING_ENABLED = "polling_enabled"
CONF_POLLING_INTERVAL = "polling_interval"          # minutes (int)

DEFAULT_POLLING_ENABLED = True
DEFAULT_POLLING_INTERVAL = 5                         # minutes == CATS_UPDATE_INTERVAL
POLLING_INTERVAL_MIN = 1                            # minutes
POLLING_INTERVAL_MAX = 1440                         # minutes (24 h)

# Petite souris polling override (Spec 047 owner addition, 2026-10-08): while
# any cat has the mode programmed, the main coordinator temporarily polls at
# the fast-polling cadence regardless of the user's polling preference; the
# preference in entry.options is preserved and restored when the mode ends.
PETITE_SOURIS_OVERRIDE_INTERVAL_MINUTES = 1          # == FAST_POLLING_INTERVAL

# Polling intervals
CATS_UPDATE_INTERVAL = timedelta(minutes=5)
ACTIVITY_UPDATE_INTERVAL = timedelta(minutes=15)
ACTIVITY_WEEK_UPDATE_INTERVAL = timedelta(hours=1)
ACTIVITY_MONTH_UPDATE_INTERVAL = timedelta(hours=6)
TERRITORY_UPDATE_INTERVAL = timedelta(minutes=15)
SESSION_UPDATE_INTERVAL = timedelta(minutes=30)
TOKEN_REFRESH_INTERVAL = timedelta(minutes=50)
FAST_POLLING_INTERVAL = timedelta(minutes=1)

# API endpoints
ENDPOINT_CATS = "/users/cats"
ENDPOINT_CAT_DETAIL = "/users/cats/{cat_id}"
ENDPOINT_ACTIVITY = "/users/cats/{cat_id}/activity"
ENDPOINT_TERRITORY_PATHS = "/users/cats/{cat_id}/territory/paths"
ENDPOINT_TERRITORY_PATH = "/users/cats/{cat_id}/territory/paths/{session_id}"
ENDPOINT_TERRITORY = "/users/cats/{cat_id}/territory"
ENDPOINT_RING = "/users/cats/{cat_id}/ring/bell-button"
ENDPOINT_PETITE_SOURIS = "/users/cats/{cat_id}/territory/petite-souris-button"


def get_polling_settings(entry) -> tuple[bool, int]:
    """Resolve polling settings from entry options with defensive defaults.

    Missing or invalid values fall back to the defaults — never to the
    nearest bound — so a corrupted or partially edited options dict can
    never produce a surprising cadence: the defaults reproduce the
    pre-1.8.0 behaviour exactly.

    Deliberate exception to constants-only: config_flow must not import
    coordinator, and every consumer already imports const.
    """
    options = getattr(entry, "options", None) or {}

    enabled = options.get(CONF_POLLING_ENABLED, DEFAULT_POLLING_ENABLED)
    if not isinstance(enabled, bool):
        enabled = DEFAULT_POLLING_ENABLED

    interval = options.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL)
    try:
        interval = int(interval)
    except (TypeError, ValueError):
        interval = DEFAULT_POLLING_INTERVAL
    else:
        if not (POLLING_INTERVAL_MIN <= interval <= POLLING_INTERVAL_MAX):
            interval = DEFAULT_POLLING_INTERVAL

    return (enabled, interval)
