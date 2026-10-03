import os
from dotenv import load_dotenv

load_dotenv()

STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID", "")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET", "")
GARMIN_EMAIL = os.getenv("GARMIN_EMAIL", "")
GARMIN_PASSWORD = os.getenv("GARMIN_PASSWORD", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# CYCLING_COACH_DB lets you point the app at another database file, for
# example a demo copy, without touching your real data.
DB_PATH = os.getenv("CYCLING_COACH_DB") or os.path.join(
    os.path.dirname(__file__), "data", "cycling.db")

def load_config():
    return {
        "strava_client_id": STRAVA_CLIENT_ID,
        "strava_client_secret": STRAVA_CLIENT_SECRET,
        "garmin_email": GARMIN_EMAIL,
        "garmin_password": GARMIN_PASSWORD,
        "anthropic_api_key": ANTHROPIC_API_KEY,
        "db_path": DB_PATH,
    }

def is_setup_complete():
    """The app opens once the Claude key is set. Garmin and Strava are
    connected afterwards from Settings, so they are not required here."""
    return bool(ANTHROPIC_API_KEY and
                ANTHROPIC_API_KEY != "paste_your_key_here")
