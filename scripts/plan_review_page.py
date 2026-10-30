"""
Write an athlete's draft program as a web page, ready to publish as a Claude artifact they can
comment on.

    venv/bin/python scripts/plan_review_page.py --list           # athletes and whether each has a draft
    venv/bin/python scripts/plan_review_page.py thomas           # writes data/plan_pages/thomas-draft.html
    venv/bin/python scripts/plan_review_page.py me --status active

Only reads the database. The page goes in data/plan_pages/, which git ignores.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import program_page  # noqa: E402
import programs  # noqa: E402
from db import profiles, schema  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("athlete", nargs="?", help="profile name, like thomas, or 'me' for the owner")
parser.add_argument("--status", default="draft", choices=("draft", "active"))
parser.add_argument("--list", action="store_true", help="show the athletes and which have a draft")
args = parser.parse_args()

if args.list or not args.athlete:
    for p in profiles.list_profiles():
        with schema.use(p["path"]):
            draft = programs.load("draft")
        print(f"{p['slug']:<20} {p['name']:<24} {'draft: ' + draft['title'] if draft else 'no draft'}")
    sys.exit(0)

found = {p["slug"]: p for p in profiles.list_profiles()}.get(args.athlete)
if not found:
    sys.exit(f"No athlete called {args.athlete!r}. Run with --list to see them.")
with schema.use(found["path"]):
    program = programs.load(args.status)
if not program:
    sys.exit(f"{found['name']} has no {args.status} program.")

out = ROOT / "data" / "plan_pages" / f"{found['slug']}-{args.status}.html"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(program_page.build_html(program, "" if found["owner"] else found["name"]), encoding="utf-8")
print(out)
