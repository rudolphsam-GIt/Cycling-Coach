"""
One-time Garmin authentication setup.

Run this ONCE from a terminal to save OAuth tokens so the app never needs
to log in again:

    cd /Users/sam/cycling-coach
    venv/bin/python scripts/garmin_setup.py

If Garmin asks for a two-factor code, enter it here and press Enter.
Tokens are saved to ~/.cycling_coach_garmin/ and reused indefinitely.
"""

import os
import sys

GARTH_DIR = os.path.join(os.path.expanduser("~"), ".cycling_coach_garmin")


def main():
    # Load credentials from .env
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    email = password = ""
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if line.startswith("GARMIN_EMAIL="):
                email = line.split("=", 1)[1].strip()
            elif line.startswith("GARMIN_PASSWORD="):
                password = line.split("=", 1)[1].strip()

    if not email or email == "your@email.com":
        email = input("Garmin email: ").strip()
    else:
        print(f"Using email from .env: {email}")

    if not password:
        import getpass
        password = getpass.getpass("Garmin password: ")

    try:
        from garminconnect import Garmin
    except ImportError:
        print("ERROR: garminconnect not installed.")
        print("Run: venv/bin/pip install 'garminconnect>=0.2.0'")
        sys.exit(1)

    print("Logging in to Garmin Connect...")
    print("(If two-factor auth is required, check your phone and enter the code below)")

    # Pre-check: detect reCaptcha lockout before garth attempts login
    try:
        import requests as _req, re as _re
        _SSO_EMBED = "https://sso.garmin.com/sso/embed"
        _H = {"User-Agent": "com.garmin.android.apps.connectmobile"}
        _PARAMS = dict(id="gauth-widget", embedWidget="true",
                       gauthHost="https://sso.garmin.com/sso")
        _SIGN = dict(id="gauth-widget", embedWidget="true",
                     gauthHost=_SSO_EMBED, service=_SSO_EMBED, source=_SSO_EMBED,
                     redirectAfterAccountLoginUrl=_SSO_EMBED,
                     redirectAfterAccountCreationUrl=_SSO_EMBED)
        _s = _req.Session(); _s.headers.update(_H)
        _s.get(_SSO_EMBED, params=_PARAMS, timeout=10)
        _r = _s.get("https://sso.garmin.com/sso/signin", params=_SIGN, timeout=10)
        _csrf_m = _re.search(r'name="_csrf"\s+value="(.+?)"', _r.text)
        if _csrf_m:
            _r2 = _s.post("https://sso.garmin.com/sso/signin", params=_SIGN, timeout=10,
                          data=dict(username=email, password=password,
                                    embed="true", _csrf=_csrf_m.group(1)))
            if "recaptcha" in _r2.text.lower() or "unexpected error" in _r2.text.lower():
                print("\n⚠️  Garmin is showing a bot-protection (reCaptcha) page.")
                print("This happens after too many failed automated login attempts.")
                print("\nTo fix this:")
                print("  1. Open garminconnect.com in your browser and log in manually")
                print("  2. Wait several hours without running this script again")
                print("  3. Then retry: venv/bin/python scripts/garmin_setup.py")
                sys.exit(1)
    except Exception:
        pass  # pre-check failed silently, let garth try anyway

    try:
        client = Garmin(email, password)
        client.login()  # will prompt for MFA code in terminal if needed
    except Exception as e:
        msg = str(e)
        if "429" in msg or "too many" in msg.lower():
            print("\n⚠️  Garmin rate-limited this IP.")
            print("Wait several hours without retrying, then run this script again.")
        else:
            print(f"\nLogin failed: {e}")
        sys.exit(1)

    os.makedirs(GARTH_DIR, exist_ok=True)
    client.garth.dump(GARTH_DIR)

    name = client.get_full_name()
    print(f"\nSuccess! Logged in as: {name}")
    print(f"Tokens saved to {GARTH_DIR}")
    print("\nGarmin sync in the app will now work without re-logging in.")


if __name__ == "__main__":
    main()
