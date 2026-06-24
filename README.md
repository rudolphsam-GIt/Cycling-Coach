# Cycling Coach

A self-hosted training dashboard and AI coach for road/gravel cyclists. Syncs
rides from Strava and Garmin Connect, computes training load (CTL/ATL/TSB),
plans workouts, preps for races, and gives Claude-powered coaching advice —
all backed by a local SQLite database, no cloud account required.

## Demo

![Cycling Coach demo](screenshots/demo.gif)

## Screenshots

> _Screenshots and demo use sample data._

**Training Dashboard** — CTL/ATL/TSB at a glance with a Performance Management Chart and daily check-in:

![Training Dashboard](screenshots/01-dashboard.png)

**Training Planner** — weekly plan plus a periodization wizard that scales a block toward a target peak CTL for your race:

![Training Planner](screenshots/02-training.png)

**Race Prep** — race calendar, taper planner, and pacing strategy:

![Race Prep](screenshots/03-race-prep.png)

**AI Coach** — chat with Claude using your actual training data as context:

![AI Coach](screenshots/04-ai-coach.png)

## Features

- **Training Load Dashboard** — CTL (fitness), ATL (fatigue), TSB (form) via a
  Performance Management Chart, daily wellness check-ins, weekly planned vs.
  actual TSS, and power/HR zone distribution.
- **Training Planner** — weekly calendar of planned workouts plus a
  periodization wizard that scales a training block from your current CTL to
  a target peak CTL ahead of a race.
- **Race Prep** — OBRA race calendar integration, taper planner, pacing
  strategy calculator, and post-race result logging.
- **Strength Training** — phase-based gym plans (off-season, build, taper)
  tailored for cycling-specific strength.
- **AI Coach** — chat with Claude using your actual training data (FTP,
  weight, CTL/ATL/TSB, recent rides, upcoming races, and stated goals) for
  specific, evidence-based coaching.
- **Competitor Research** — pulls OBRA public race results to scout fields
  and generate race tactics briefs.
- **Onboarding questionnaire** — new athletes pick their goals (speed,
  endurance, weight loss, race prep, general fitness), experience level, and
  weekly training hours; the app estimates starting FTP/LTHR/CTL and tailors
  AI Coach advice accordingly.

## Technical highlights

- **Training-load model** — computes the Performance Management Chart from daily
  TSS: CTL as a 42-day rolling average, ATL as a 7-day average, TSB as
  yesterday's CTL − ATL, with a forward projection that scales a planned-TSS
  schedule toward a target peak CTL for race day.
- **Cross-source deduplication** — Strava, Garmin, and `.fit`/`.csv` imports all
  upsert into SQLite keyed on a source-tagged `external_id`, then a dedup pass
  collapses the same ride seen by two devices (matched on date + duration within
  5 min + distance within 10% or 500 m), keeping the richer record.
- **Resilient ingestion** — Strava OAuth with automatic token refresh, Garmin
  `garth` auth with saved-token reuse and a manual import fallback when Garmin
  rate-limits.
- **Context-aware AI coach** — builds a snapshot of the athlete's real data
  (FTP, weight, CTL/ATL/TSB, recent rides, upcoming races, goals) and feeds it to
  Claude (`claude-sonnet-4-6`) so coaching advice is grounded, not generic.
- **OBRA integration** — scrapes the public race schedule and results for the
  race calendar and competitor-scouting briefs.

## Data sources

- **Strava** (OAuth) and **Garmin Connect** (garth-based auth) for activity
  sync, with automatic cross-source deduplication.
- Manual **.fit / .csv** ride import as a fallback when Garmin auth is
  rate-limited.
- **OBRA** (Oregon Bicycle Racing Association) public schedule and results
  for race calendar and competitor research.

## Stack

Python · Streamlit · SQLite · Plotly · Anthropic Claude API

## Setup

```bash
cp .env.example .env   # fill in your API keys
bash setup.sh
bash start.sh
```

See `.env.example` for required keys (Strava, Garmin, Anthropic). Garmin
auth requires a one-time interactive login — run `scripts/garmin_setup.py`
once if Garmin shows a bot-protection challenge.

## Project layout

```
app.py                  Entry point — setup gate, onboarding gate, navigation
pages/                  Dashboard, Training Planner, Race Prep, Strength,
                         AI Coach, Competitors, Settings
db/                     SQLite schema + queries
auth/                   Strava OAuth, Garmin auth, .fit/.csv import
metrics/                Training load (CTL/ATL/TSB) and zone estimation
research/               OBRA schedule + race results scraping
components/             Shared UI (styles, cards, onboarding)
scripts/                One-off setup scripts (Garmin auth)
```

Single-user by design — each person runs their own copy with their own
`.env` and local database.

## License

MIT — see [LICENSE](LICENSE).
