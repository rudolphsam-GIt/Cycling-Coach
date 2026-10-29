"""
Print the Google Apps Script that builds the athlete intake form. The questions live in
intake_form.py.

    venv/bin/python scripts/make_intake_form.py | pbcopy

Then paste it into a new project at script.google.com, pick createIntakeForm and press Run.
The form link, its edit link and the response sheet show in the execution log.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from intake_form import apps_script  # noqa: E402

print(apps_script(), end="")
