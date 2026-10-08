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

# Secondary polling intervals (Spec 048) — minutes (int), per coordinator.
# Reuse POLLING_INTERVAL_MIN / POLLING_INTERVAL_MAX (047) as the shared bounds.
CONF_POLLING_INTERVAL_ACTIVITY = "polling_interval_activity"
CONF_POLLING_INTERVAL_ACTIVITY_WEEK = "polling_interval_activity_week"
CONF_POLLING_INTERVAL_ACTIVITY_MONTH = "polling_interval_activity_month"
CONF_POLLING_INTERVAL_TERRITORY = "polling_interval_territory"
CONF_POLLING_INTERVAL_SESSION = "polling_interval_session"

DEFAULT_POLLING_INTERVAL_ACTIVITY = 15          # == ACTIVITY_UPDATE_INTERVAL
DEFAULT_POLLING_INTERVAL_ACTIVITY_WEEK = 60     # == ACTIVITY_WEEK_UPDATE_INTERVAL
DEFAULT_POLLING_INTERVAL_ACTIVITY_MONTH = 360   # == ACTIVITY_MONTH_UPDATE_INTERVAL
DEFAULT_POLLING_INTERVAL_TERRITORY = 15         # == TERRITORY_UPDATE_INTERVAL
DEFAULT_POLLING_INTERVAL_SESSION = 30           # == SESSION_UPDATE_INTERVAL

# key = hass.data / coordinator name -> (option key, default minutes)
SECONDARY_POLLING_INTERVALS = {
    "activity":        (CONF_POLLING_INTERVAL_ACTIVITY, DEFAULT_POLLING_INTERVAL_ACTIVITY),
    "activity_week":   (CONF_POLLING_INTERVAL_ACTIVITY_WEEK, DEFAULT_POLLING_INTERVAL_ACTIVITY_WEEK),
    "activity_month":  (CONF_POLLING_INTERVAL_ACTIVITY_MONTH, DEFAULT_POLLING_INTERVAL_ACTIVITY_MONTH),
    "territory":       (CONF_POLLING_INTERVAL_TERRITORY, DEFAULT_POLLING_INTERVAL_TERRITORY),
    "session":         (CONF_POLLING_INTERVAL_SESSION, DEFAULT_POLLING_INTERVAL_SESSION),
}

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


def _resolve_int_minutes(value, default: int) -> int:
    """Coerce an options value to an in-range minute count (Spec 048 §2.2).

    Falls back to `default` — never to the nearest bound — when the value
    is not int-coercible (TypeError/ValueError, incl. None and "15.9") or
    outside the shared 047 bounds. int()-coercible strings are accepted
    ("30" -> 30) and floats truncate through int() (15.9 -> 15), mirroring
    the inherited 047 semantics.
    """
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return default
    if not (POLLING_INTERVAL_MIN <= minutes <= POLLING_INTERVAL_MAX):
        return default
    return minutes


def get_secondary_polling_intervals(entry) -> dict[str, int]:
    """Resolve the five secondary polling intervals (minutes) with defensive defaults.

    Returns the full five-key dict {"activity": …, "activity_week": …,
    "activity_month": …, "territory": …, "session": …} keyed by the
    hass.data / coordinator names, in the fixed SECONDARY_POLLING_INTERVALS
    order. Per key (Spec 048 §2.2, mirroring 047 §2.2): a missing,
    non-coercible or out-of-range value falls back to that coordinator's
    DEFAULT — never to the nearest bound — so a corrupted or partially
    edited options dict can never produce a surprising cadence; the
    defaults reproduce the 1.8.0 behaviour exactly. Never raises;
    tolerates an entry with no options attribute.

    Same deliberate exception to constants-only as get_polling_settings:
    config_flow must not import coordinator, and every consumer already
    imports const.
    """
    options = getattr(entry, "options", None) or {}
    return {
        name: _resolve_int_minutes(options.get(option_key), default)
        for name, (option_key, default) in SECONDARY_POLLING_INTERVALS.items()
    }
