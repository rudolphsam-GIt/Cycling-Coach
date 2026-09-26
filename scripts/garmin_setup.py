"""
Backup way to connect Garmin from a terminal, if connecting in Settings fails.

    cd ~/cycling-coach
    venv/bin/python scripts/garmin_setup.py

Enter your Garmin email and password, and the verification code if Garmin
sends one. Tokens are saved to ~/.cycling_coach_garmin/ and refresh on their own.
"""

import getpass
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import run_migrations  # noqa: E402
import auth.garmin as garmin_auth  # noqa: E402


def main():
    run_migrations()
    email = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password: ")
    try:
        status, state = garmin_auth.start_login(email, password)
        if status == "needs_code":
            garmin_auth.finish_login(state, input("Verification code from Garmin: "))
    except Exception as e:
        print(garmin_auth.friendly_error(e))
        sys.exit(1)

    print("Connected. Pulling your last 90 days…")
    _, msg = garmin_auth.sync(days_back=90)
    print(msg)


if __name__ == "__main__":
    main()
