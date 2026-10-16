# Cycling Coach

A Streamlit training app that runs locally. It syncs rides from Garmin, Strava and TrainingPeaks, tracks fitness and fatigue, keeps a training calendar, and has an AI coach (Claude) that plans workouts and reviews rides. See README.md for features and setup.

## Running and testing

- Run the app with the `cycling-coach` launch config (port 8599). Use `cycling-demo`, `cycling-empty` or `cycling-onboarding` to try changes against a throwaway database, never the real one.
- Real training data lives in `data/cycling.db` (and `data/profiles/` for coached athletes). Back it up before any migration or bulk change, named like `data/cycling-before-<change>-<date>.db`.
- Tests: `./venv/bin/python -m pytest tests`. Use `./venv/bin/python`, not the system Python. `venv-py39` is an old leftover.

## How Sam likes to work

- One change at a time. Show the diff and test results, then wait for an OK before starting the next change.
- Work on a branch, test, merge to main, push.
- Research in `knowledge/` is a set of suggestions the athlete can accept or change, never hard rules. Only safety and medical rules are firm. Always report the evidence strength and pool size (studies, people, who) and flag runner or observational data.
- TSS and fitness methods follow published standards (Coggan TSS, normalized TRIMP). No fudge factors.
- Do not push an FTP goal or "on track" card on riders. Watch how the body responds instead.
- Say so when a chat is getting too long and suggest continuing in a new one.

## Code notes

- `ftp_change.apply_new_ftp` is the only way to set FTP. It rescales watts in upcoming workouts and resends them to Garmin.
- Background workers and lazy downloads must use `schema.pinned`, or they hit the owner database instead of the selected athlete.
- The coach must call `get_training_research` before planning. `knowledge/principles.md` rides in every system prompt.
