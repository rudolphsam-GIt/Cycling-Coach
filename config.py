import os
from dotenv import load_dotenv

load_dotenv()

STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID", "")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET", "")
GARMIN_EMAIL = os.getenv("GARMIN_EMAIL", "")
GARMIN_PASSWORD = os.getenv("GARMIN_PASSWORD", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "cycling.db")

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
    """Check if the user has at least one data source and Claude configured."""
    has_strava = bool(STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET and
                      STRAVA_CLIENT_ID != "paste_your_client_id_here")
    has_garmin = bool(GARMIN_EMAIL and GARMIN_PASSWORD and
                      GARMIN_EMAIL != "your@email.com")
    has_claude = bool(ANTHROPIC_API_KEY and
                      ANTHROPIC_API_KEY != "paste_your_key_here")
    return (has_strava or has_garmin) and has_claude
