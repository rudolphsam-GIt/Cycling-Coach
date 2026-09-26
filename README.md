# Cycling Coach

A self-hosted training dashboard and AI coach for road/gravel cyclists. Syncs
rides from Strava and Garmin Connect, computes training load (CTL/ATL/TSB),
plans workouts, preps for races, and gives Claude-powered coaching advice —
all backed by a local SQLite database, no cloud account required.

## Features

- **Today** — one screen for the day: today's planned workout, last night's
  Garmin recovery (sleep, HRV, resting HR, readiness), a quick "how do you
  feel" check-in, fitness/fatigue/form, and your coach's review of your latest
  ride. Below that, the Performance Management Chart, weekly planned vs. actual
  TSS, and power/HR zone distribution.
- **Ride reviews** — after each synced ride, the coach writes a short review:
  how it compared to the plan, what it did to fitness and fatigue, and what
  tomorrow should look like.
- **Weekly check-in** — the coach reviews the week (load, key sessions,
  recovery trend) and drafts the next 7 days for you to confirm.
- **Race day plan** — for any race on your calendar: a day-by-day taper, race
  morning routine, power and heart rate pacing targets, fueling, and a
  checklist.
- **Coach memory** — tell the coach about an injury, your schedule or your
  preferences once and it remembers; you can see and delete every note.
- **Training Planner** — weekly calendar of planned workouts plus a
  periodization wizard that scales a training block from your current CTL to
  a target peak CTL ahead of a race.
- **Race Prep** — OBRA race calendar integration, taper planner, pacing
  strategy calculator, and post-race result logging.
- **Strength Training** — phase-based gym plans (off-season, build, taper)
  tailored for cycling-specific strength.
- **AI Coach** — chat with Claude using your actual training data (FTP,
  weight, CTL/ATL/TSB, recent rides, upcoming races, and stated goals) for
  specific, evidence-based coaching. Replies stream in as they're written, the
  coach looks up deeper history on its own when a question needs it, and you
  can attach screenshots of workouts or charts. Ask it to plan your week and
  it proposes workouts you confirm with one click before they hit the planner.
- **Competitor Research** — pulls OBRA public race results to scout fields
  and generate race tactics briefs that cite the specific result behind every
  claim about a rival.
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
  Claude Opus 5.5 (`claude-opus-5-5`) so coaching advice is grounded, not generic.
- **Tool-using agent loop** — the coach streams its reply while calling
  read-only tools over the SQLite data (ride history, PMC, weekly zone totals,
  wellness, FTP history, planner). Tool inputs are validated before they run,
  and the one write action, proposing workouts, only takes effect after the
  athlete confirms in the UI.
- **OBRA integration** — scrapes the public race schedule and results for the
  race calendar and competitor-scouting briefs.

## Data sources

- **Strava** (OAuth) and **Garmin Connect** (garth-based auth) for activity
  sync, with automatic cross-source deduplication.
- **Garmin Connect** recovery data: sleep, HRV, resting HR, training
  readiness and body battery, synced alongside rides.
- Manual **.fit / .csv** ride import as a fallback.
- **OBRA** (Oregon Bicycle Racing Association) public schedule and results
  for race calendar and competitor research.

## Stack

Python · Streamlit · SQLite · Plotly · Anthropic Claude API

## Setup

```bash
bash setup.sh          # installs Python 3.12 via uv if needed, then packages
bash start.sh
```

Add your `ANTHROPIC_API_KEY` to `.env`. Then connect **Garmin** from
Settings → Connections: sign in once (with your 2FA code if Garmin asks) and
rides plus recovery sync automatically whenever you open the app. Strava is
also supported. If connecting in the app fails, `venv/bin/python
scripts/garmin_setup.py` does the same from a terminal.

## Project layout

```
app.py                  Entry point — setup gate, onboarding gate, navigation
pages/                  Today, Plan, Coach, Strength, Races, Competitors,
                         Settings (grouped into Train / Race / Account)
claude_client.py        Claude calls: streaming, tool loop, errors, fallbacks
coach_tools.py          Tools the coach can call over your data
coach_context.py        Coach persona + athlete snapshot shared by every AI feature
coach_reports.py        Ride review, weekly check-in and race plan prompts
db/                     SQLite schema + queries
auth/                   Strava OAuth, Garmin auth, .fit/.csv import
metrics/                Training load (CTL/ATL/TSB) and zone estimation
research/               OBRA schedule + race results scraping
components/             Shared UI (styles, cards, onboarding, coach UI)
.streamlit/config.toml  Dark theme
scripts/                One-off setup scripts (Garmin auth)
```

Single-user by design — each person runs their own copy with their own
`.env` and local database.

## License

MIT — see [LICENSE](LICENSE).
