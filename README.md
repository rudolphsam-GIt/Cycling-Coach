# Cycling Coach

Cycling Coach is a training app that runs on your own computer. It pulls in your rides from Garmin (or Strava), tracks your fitness and fatigue, and keeps a training calendar.

It also has an AI coach you can chat with. The coach sees your real training numbers, so it can plan workouts, review rides and help you prepare for races.

Your training history stays in a local database on your machine. Nothing is stored in the cloud by this app.

## New to structured training?

You do not need to know any of the jargon to start. Here are the five ideas the app is built on, in plain words.

1. **FTP** is the most power you can hold for about an hour. It is your yardstick. If you do not know it, the app starts with an estimate and can suggest a better one from your best 20 minutes, or plan a guided test.
2. **Zones** are effort bands based on your FTP. Zone 2 is steady, comfortable riding and should make up most of your time. Higher zones are harder and make you faster, but only a little of your riding should be there.
3. **TSS (training stress score)** is one number for how big a ride was, counting both how long and how hard. One hour at your FTP is 100. It lets you add up a week and see how much you are asking of your body.
4. **Fitness and fatigue.** Fitness (CTL) is your training load averaged over about six weeks. It rises when you train consistently. Fatigue (ATL) is the same over about a week, so it jumps after hard days.
5. **Form** is fitness minus fatigue. Slightly negative is normal and productive while you train. You want to be positive when you race, and very negative for weeks is a warning.

How the app helps you learn.

- **Help icons and tooltips.** Look for the small question mark icons and the hover tips next to numbers and charts. Each one says what it is, why it matters, and what your own number means right now.
- **Your coach explains the why.** Every workout the coach plans says what it is for in terms of your goals, what to focus on, and how it should feel (effort out of 10 and a talk test). Every block explains what each phase is building. On the calendar, hover or open a workout to read it. The same text goes to your Garmin if you send the workout.
- **Getting started checklist.** On the Today page, a short list of the steps to set up, which ticks itself off from your data.
- **Build my first block.** One button that asks the coach for a gentle four week starting block. Setup asks for your goals in your own words (with examples to get you thinking), how many hours a week and how many days a week you can train, and the plan is built to fit them. You can change all three later in Settings.
- **Help finding your FTP, with no pressure.** Not knowing your FTP is completely normal, so setup gives you three choices. 1) I know it, and you type it in. 2) I don't know it, but I'm happy to do a test. 3) I don't know it and would rather not test, so please estimate it for me. For the last two, three short questions pick a typical starting range for someone like you: what kind of rider you are (new to cycling, ride without a plan, followed a training plan, or race), how active you are, and your gender (Woman, Man, Non-binary or Prefer not to say), because typical power per kilo is lower for women than for men (about 15 percent at the beginner level, which is in line with the published Allen and Coggan tables). It is used only to pick typical power ranges. Non-binary and Prefer not to say use an average of the two, and anyone can choose either reference table on the Dashboard power profile. Gender and age sit on one line. Your weight is asked for anyway. Age is optional. Power drops by roughly 1 percent a year after about 35, so a 55 year old starts about 15 percent lower than someone in their thirties, and a younger rider under 18 a little lower too. Age also sets your starting threshold heart rate. Only your birth year is stored, so your age stays current. Activity is spelled out so nobody has to guess (for example moderately active is 3 to 4 sessions and about 3 to 5 hours a week with some harder efforts). A newcomer might see 85 to 125 watts, and the app starts you in the middle. If you choose the test, your first training block includes it, described for newer riders as a steady pace with no pass or fail. If you choose the estimate, no test is scheduled and the estimate is refined from your rides. Either way, once rides are in, the Today page and Settings offer 95% of your best 20 minutes, and you can add the test to your plan whenever you like. The card on Today only appears when your best 20 minutes would raise your FTP, and it has three buttons: use the suggestion, plan a test, or Not now, which hides it for 14 days. Enter it myself opens a small box to type your own number. Settings always shows the suggestion, including when it is lower than your current FTP, with an explanation.
- **Pounds or kilograms, miles or kilometers.** A lb and kg switch appears wherever you enter weight (setup, Settings and the Strength page). A mi and km switch sets distance everywhere: setup, Settings, and the filter bar on the Dashboard and Data pages. Choosing miles also shows climbing in feet and speed in mph, and applies to the calendar hover, ride tables, the ride analysis, the Dashboard tiles and charts, race distances and the pacing planner. Both choices are remembered, and your coach is told so it speaks in the same units.

## What you need

1. A Mac or Linux computer.
2. Python 3.12. You do not need to install it yourself, because `setup.sh` installs it for you using a tool called uv. It does not touch the Python that came with your computer.
3. An Anthropic API key. This is what powers the coach. See "Getting an Anthropic API key" below.
4. A Garmin Connect account if you want rides and recovery data to sync automatically. This is optional and you connect it after the app is running.

## Setup

1. Open a terminal and go to the project folder.
2. Run the setup script. It needs an internet connection and takes a minute or two.

   ```
   bash setup.sh
   ```

3. Open the new file called `.env` in a text editor. Find the line that starts with `ANTHROPIC_API_KEY=` and paste your key after the equals sign, replacing the placeholder text. Save the file.
4. Start the app.

   ```
   bash start.sh
   ```

5. Your browser should open on its own. If it does not, open the address the terminal prints, which is normally http://localhost:8501.

The app opens as soon as the Anthropic key is in place. Garmin and Strava are connected afterward from the Settings page. The Strava lines in `.env` are optional and only matter if you want to use Strava. The Garmin email and password lines in `.env` are also optional. If you fill them in, Settings pre fills the Garmin sign in form for you.

To stop the app, press Control and C in the terminal. Next time, you only need `bash start.sh`.

## Getting an Anthropic API key

The coach talks to Anthropic's API directly using your own key. It does not use a Claude subscription, so a Claude.ai plan will not work here and API use is billed to your key.

1. Go to https://console.anthropic.com and create an account or sign in.
2. Add a payment method or credit to the account if the console asks for one.
3. Open the API Keys section and create a new key.
4. Copy the key right away, because the console will not show it again. Paste it into `.env` as described above.

You pay for what you use, based on how much text goes back and forth. Short questions cost little. Long conversations, screenshots, and building a multi week plan cost more, because the coach reads a lot of your training data each time. Check the pricing page in the console for current rates, and consider setting a monthly spend limit there so you never get a surprise. To keep costs down, short routine jobs (the ride review and turning a workout into Garmin steps) run on a cheaper model, and the weekly check in uses medium effort. Planning, plan edits and chat use the strongest model. Anything you do not use the coach for (the calendar, charts, strength logging, .fit export) costs nothing.

## Connecting Garmin

You do this once, from the Settings page, after the app is running.

1. Open Settings and choose the Connections tab.
2. Under Garmin, enter your Garmin Connect email and password and press Connect Garmin.
3. If your Garmin account uses two step verification, Garmin sends you a code by email or text. Enter it and press Verify. If the code expires, press Cancel and start again.
4. The app pulls your last 90 days of rides and recovery data.

After that, new rides and recovery data sync on their own whenever you open the app and it has been a few hours since the last sync. You can also press "Sync Garmin now" in Settings.

What syncs from Garmin is your cycling activities (duration, distance, elevation, heart rate and power) plus sleep, heart rate variability, resting heart rate, readiness and body battery. Not every watch records all of these, and anything missing is simply skipped.

Your password is only used to sign in. After that the app keeps sign in tokens in a folder called `.cycling_coach_garmin` in your home folder, and it does not need your password again. Pressing Disconnect Garmin in Settings deletes the token file.

If connecting from the app does not work, you can do the same thing from the terminal. From the project folder run:

```
venv/bin/python scripts/garmin_setup.py
```

It asks for your email, password and verification code, saves the tokens in the same place, and pulls 90 days of history.

If you do not use Garmin, you can connect Strava instead on the same Connections tab (it needs the Strava keys in `.env`), or import `.fit` and `.csv` files by hand from the "Import .fit or .csv files by hand" section under Garmin.

## First run

The first time you open the app after setup, a short welcome form asks about you.

1. Your name.
2. Your main goals. You can pick more than one.
3. Your training experience.
4. How many hours a week you can train.
5. Your weight.
6. Your FTP and threshold heart rate, if you know them. If you do not, the app estimates a starting point from your experience level and refines it as you train.
7. Optionally, a race you are training for.

You can change all of this later in Settings under Profile. It is worth setting your real FTP there as soon as you know it, because training stress scores and zones are based on it.

## A guide to each page

### Today

Your daily screen. It shows today's planned workout, last night's recovery from Garmin (if your watch has not synced to Garmin Connect for more than a day, the card shows the date of the last data and tells you to open the Garmin Connect app, instead of looking like the connection is broken), and a quick check in where you rate how your legs and energy feel. Below that are your fitness, fatigue and form numbers, your coach's review of your latest ride, and a summary of planned versus actual training stress for the week. Further down you will find your fitness history chart, your recent rides, and zone breakdowns.

Fitness, fatigue and form are calculated the way TrainingPeaks does it. Fitness (CTL) is a 42 day exponentially weighted average of daily training stress. Fatigue (ATL) is the same with a 7 day window. Form is yesterday's fitness minus yesterday's fatigue. Positive form means you are fresh and a very negative form means you are carrying a lot of fatigue.

### Plan

The Plan page has three tabs.

**Calendar.** A month grid of everything planned and everything you did. Hover over a day to see details, drag an upcoming workout to another day, and click a workout to open it and edit it. Under the grid, a Plan impact panel shows how the plan changes your fitness, fatigue and form. See "Using the calendar" below.

**Coach.** Chat with your AI coach. It can propose single workouts or a whole block of weeks, including strength sessions. It also holds your coach memory and the weekly check in. See "Chatting with the coach" below.

**Manage.** Lists of this week's workouts and everything upcoming. From here you can send a whole week to Garmin or download a whole week as `.fit` files. Quick Generate is also here. It builds a training block toward a race from your current fitness and a target peak fitness, without any conversation. It adds workouts straight to your plan, and you can edit or remove them afterward.

### Dashboard

Charts for any date range, in the spirit of the TrainingPeaks dashboard. Pick a range at the top (7 days up to a year, all time, or custom dates), and optionally search or filter rides. Summary tiles show rides, time, distance, climbing, training stress, work, average intensity factor and average efficiency factor, each compared with the period of the same length just before. Below that are four tabs.

1. Load. The performance chart (fitness, fatigue, form and daily training stress), weekly volume as training stress, hours, distance or climbing, and planned versus done per week.
2. Power. Your peak power curve (best 5 seconds up to 2 hours) against the period before or your all time best, a table of key durations in watts and W/kg, power and intensity per ride, efficiency factor over time, FTP history and time in zones.
3. History. Fitness history tables like the ones in TrainingPeaks, one for peak power and one for peak heart rate. Rows are the current week and the three before it, the current month and the twelve before it, and an All time row. Columns are moving time, distance (switch between km and mi), training stress, work in kJ, and your best 5 seconds, 1, 5, 20 and 60 minutes. The week and month still in progress are in grey. Below them is your power profile, your best power per kilo at those durations placed on the Allen and Coggan categories from Untrained up to World class, for the selected dates or all time, on the men's or women's chart.
4. Recovery. HRV, resting heart rate, sleep and readiness from Garmin, with form behind them so you can read recovery against load.

The search and filters change the tiles and the ride charts. Fitness, fatigue and form always count every ride, since all of it is load. The page only loads when you open it, and each tab only draws when you select it.

Peak power comes from Garmin's ride summaries. Peak heart rate is worked out from each ride's file, which the app downloads from Garmin, with stops cut out the way TrainingPeaks does it. New rides get both when they sync. For older rides, open Settings, Connections, and use Load peak power and heart rate history. It fills in the last year for rides already in the app, adds no rides, and takes a minute or two the first time. `.fit` files you import by hand get both too. Rides that only came from Strava have neither.

### Data

Search and filter your rides. Type words from a ride name (every word has to match, in any order), and use More filters for ride type (road, indoor, gravel, mountain), training stress, intensity factor, moving time, distance, and only rides with power or heart rate. The same summary tiles as the Dashboard sit above a sortable table of the rides. Select a row to open the ride, or download the list as a CSV file. Your search carries over to the Dashboard and back. Clear resets everything except the date range.

**Zooming charts.** On any chart over time, drag across the dates you want to look at and the chart zooms to them. Only the dates zoom, so the vertical scale stays the same. Press Reset zoom above the chart, or double click the chart, to see the full range again.

### Strength

Gym plans for cyclists, in three phases (off season and base, build, and race season maintenance). Pick a phase to see the sessions and exercises, then log a session you completed with the weights you used.

If your coach plans a strength session for you in the chat, it shows up at the top as "Planned by your coach". Open it, enter the duration and the weights you lifted, and save. Logging it counts the session toward your progress and marks it done on the calendar.

The Strength Progress chart at the bottom shows the weight you lifted over time for each exercise you have logged weights for.

### Races

Your race calendar and race tools. It has four tabs.

1. Race Day Plan. The coach builds a day by day taper, race morning routine, pacing targets and fueling plan for a race you pick.
2. Calendar. Add races, either by picking one from the OBRA schedule (Oregon Bicycle Racing Association) or by entering your own, and log results afterward. Races show up on the Plan calendar too.
3. Taper. A taper planner that can add taper workouts to your plan.
4. Pacing. A pacing and nutrition calculator for a course you describe.

### Competitors

Scouting for races on the OBRA calendar. You load a field of riders from an OBRA event (or paste names), and the app looks up their public race results. It then writes a tactics brief that points to the specific results behind each claim. It is built around OBRA, so it is most useful if you race in that region.

### Settings

Three tabs.

1. Profile. Your goals, FTP, threshold heart rate, weight and starting fitness.
2. Connections. Connect and sync Garmin and Strava, import `.fit` or `.csv` files by hand, and load peak power and heart rate history from Garmin.
3. Data tools. Recalculate training stress for every ride (useful after you change your FTP) and remove duplicate rides that came in from both Garmin and Strava.

## Using the calendar

The Calendar tab on the Plan page shows one month at a time. Use the arrows to change months.

**What the colors mean**

| Marker | Meaning |
|---|---|
| Planned | A workout is planned for today or a future day. |
| Done | A past planned workout and you rode that day. |
| Short of plan | You rode, but your actual training stress was under 70 percent of what was planned. |
| Missed | A past planned workout and no ride that day. |
| Unplanned ride | You rode on a day with nothing planned. |

Strength sessions and races also get their own markers on the day they happen. Today has an outline around it. Days with nothing planned and no ride are left plain.

**Looking at a day.** On a computer, hover over a day to see what was planned or done. This includes the workout name and description, and for a ride the duration, distance, power and training stress. On a phone or tablet, tap the day. If you would rather not use the grid, there is also a date picker with Previous, Next and Today buttons right under it.

**Moving a workout.** Drag an upcoming workout (or planned strength session) from one day to another. It moves right away and a bar under the calendar offers Undo. Only workouts planned for today or later that are not marked done can be moved. Past days and done workouts stay where they are. If the workout was already sent to Garmin, the old Garmin copy is removed and the workout shows as needing a send again, so send it for the new day. Dragging does not work on a touch screen. Tap the workout instead and change its date in the window that opens.

**Opening a workout.** Click a workout on the grid, or use Edit in the Manage tab, to open it in a window. Change the name, type, date, planned training stress or description, then save. Before you save, the window shows what the change would do to your fitness, fatigue and form, and flags problems such as back to back hard days or a big jump in weekly training stress. You can also mark the workout done, remove it, send it to Garmin or download it as a `.fit` file from there.

**Analyzing a ride you have done.** Click a ride you did (the green entries on past days) and a window opens with that ride. At the top are the numbers (time, distance, climbing, TSS, average and normalized power, intensity, variability, heart rate, work and efficiency) and a note on pacing, which compares your power to heart rate ratio in the first and second half of a long ride. Below are tabs. Timeline charts power, heart rate, speed, cadence and elevation, with smoothing you can choose and drag to zoom. The top and bottom of the chart are marked in miles or kilometers (the bottom also shows the clock time), so you can see where on the road each effort happened, and the marks re-scale as you zoom in. Zones and efforts shows your time in each power and heart rate zone and lists the hard stretches. Power curve compares this ride's best power with your best ever. Plan shows what was planned that day next to what you rode, with the purpose and how it should feel. Coach reads the ride against your plan and recovery. The charts need second by second data, which the app fetches from Garmin or Strava the first time you open a ride (or reads from a `.fit` file you imported) and keeps, so each ride is only fetched once. Speed is included, as average and maximum speed in the numbers and as its own row on the timeline. **Zoom in on part of the ride.** Drag across the timeline and the popup zooms to that section and locks it in for everything at once: the timeline itself, the numbers at the top (time, distance, climbing, TSS, power, speed, cadence, heart rate and the rest), the pacing note, the zones and efforts, and the power curve. A banner says exactly which minutes you are looking at and how that compares with the whole ride. Drag again inside it to go deeper, as many times as you like. Back goes up one level and Whole ride returns to the full ride. Without second by second data you still get the numbers and estimated zones. The same window opens from the Data page with Analyze this ride.

**Removing strength sessions.** Open a strength session on the calendar (or from the day panel, the Strength page, or the planned session list) and press Remove. A session you already logged asks you to tick a box first, because the weights you recorded go with it.

**Plan impact.** The panel under the calendar projects your fitness (CTL), fatigue (ATL) and form (TSB) up to your next race, or four weeks out if no race is coming up. It assumes you ride the plan exactly as written, so it is a projection and not a prediction. Only workouts still to come count, so a ride you already did today never looks like the plan. If nothing is planned from today on, the panel says so instead of projecting a drop in fitness. If your plan stops well before that day, the panel says so, because the numbers then assume rest after the last planned workout. After you move a workout, the cards show what that move changed and the chart shows the before and after. It uses the same method as TrainingPeaks, so the numbers match the Today page. Strength sessions are not counted in training load.

**Working with a day.** Click a day to open it below the calendar. From there you can do the following.

1. Open a planned workout to edit it or remove it. Removing a workout that was sent to Garmin also removes it from Garmin.
2. Mark a workout done, and undo that if you tapped it by mistake.
3. Send a workout to Garmin, or download it as a `.fit` file.
4. Add a workout on that day. Pick the date, type, and training stress, and write a description.

**One thing to know.** The calendar matches planned workouts to rides by date only. If you planned a workout for Tuesday and rode on Tuesday, it counts as done, even if the ride was a different workout. Planned workouts are not tied to specific rides. If you do two rides in one day, both count toward that day's total. The status colors are worked out when you look at the calendar and are never saved, so they always reflect the latest ride data.

## Chatting with the coach

The Coach tab is where most of the planning happens.

1. Use the starter questions if you are not sure where to begin. They change depending on whether you have a race coming up.
2. Be specific about your week. Tell the coach which days you can ride, how long you have, and what your goal is. If you have a race, say so, or add it on the Races page first and the coach will know about it.
3. Ask for a block. For example, "Build me a six week block toward my race with two strength sessions a week." The coach proposes the rides and strength sessions together.
4. **Your coach can change your calendar and plan.** Ask it to move a workout, shorten or rename one, skip a day, or drop a strength session ("I'm travelling Thursday, can you rearrange the week?"). It looks up what is on your plan, then shows a list of proposed changes with the reason for each. Nothing changes until you press Apply changes, and only today and later, not yet done, can be changed. A workout that was already sent to Garmin has its old copy removed so you can send it again for the new day.
5. Nothing is saved until you say so. Proposed workouts appear in a card right under the reply. Read them, then either add them all to your plan or discard them. If something is off, tell the coach what to change and it will propose again. You can open them on the calendar afterward to see where they landed.
6. Attach a screenshot. You can attach an image of a workout, a training plan or a chart with your message, and the coach will read it. The image is used for that message only and is not kept in the chat history.
7. Tell the coach about injuries, your schedule or your preferences once. It saves a note in its memory. Open "What your coach remembers" to read the notes and delete any you do not want kept.
8. Run the weekly check in. The coach looks over your week and drafts the next seven days for you to confirm. Past check ins are kept so you can look back.
9. Clear the chat when you want a fresh start. This removes the saved conversation but keeps your plan, your memory notes and your ride data.

The coach can look up your full ride history, weekly totals, check ins and FTP history on its own when a question needs it, so you do not need to paste numbers in.

## Sending workouts to Garmin and TrainingPeaks

**Garmin.** Garmin must be connected in Settings first. Use the Send to Garmin button on a workout, or send a whole week from the Manage tab. The coach turns the written workout into steps with power targets based on your FTP and shows you a preview. When you confirm, the workout is uploaded to Garmin Connect and scheduled on its date, so it syncs to your Garmin watch or bike computer. If you edit or delete the workout later, the Garmin copy is updated or removed to match. A workout that you changed after sending shows as needing a resend.

**.fit files for TrainingPeaks.** TrainingPeaks cannot be linked from this app, but you can move workouts across by hand. Use the Download .fit button on a single workout, or download a whole week from the Manage tab. One workout gives you one `.fit` file. Several workouts give you one zip file with a `.fit` file for each. Then upload the files to TrainingPeaks yourself using its workout import. The same `.fit` files work with other tools that accept structured workouts.

## Data and privacy

Where things are kept.

1. Your rides, plans, settings, chat history and coach memory are in `data/cycling.db` inside the project folder. This file is listed in `.gitignore`, so it is never committed to git.
2. Your API keys are in `.env`, which is also in `.gitignore`.
3. Your Garmin sign in tokens are in `.cycling_coach_garmin` in your home folder, outside the project.

What leaves your computer.

1. When you use the coach, a summary of your training (FTP, weight, fitness numbers, recent rides, races, goals), your chat messages, your coach memory notes and any screenshots you attach are sent to the Anthropic API. The same goes for ride reviews, weekly check ins, race plans and sending workouts to Garmin, which also use the coach.
2. Sync talks to Garmin or Strava. Race features fetch public pages from the OBRA website.
3. Nothing else is uploaded. If you never press a coach button and never send a chat message, no training data goes to Anthropic.

To back up your data, stop the app and copy `data/cycling.db` somewhere safe. To restore, put the copy back in the same place.

To delete your data, stop the app and delete `data/cycling.db`. To forget your Garmin login, press Disconnect Garmin in Settings or delete the `.cycling_coach_garmin` folder in your home folder. To revoke the coach's access, delete the API key in the Anthropic console and remove it from `.env`.

**Trying the app on demo data.** You can run the app against a fake database and leave your real data alone. This builds about three months of made up rides, plans, strength sessions and a race.

```
venv/bin/python scripts/seed_demo_db.py /tmp/demo.db
CYCLING_COACH_DB=/tmp/demo.db bash start.sh
```

Add `--empty` to the first command to get a database with settings but no rides or plans. The setting `CYCLING_COACH_DB` works with any file path, so it is also a handy way to keep a separate database for a second athlete. You still need an Anthropic key in `.env` to open the app, but nothing is spent unless you use the coach.

## Troubleshooting

**The setup page will not go away.** The app only needs `ANTHROPIC_API_KEY` in `.env`. Check that the file is named exactly `.env` (not `.env.txt` or `.env.example`), that it sits in the project folder next to `app.py`, that there are no spaces around the equals sign, and that the key is not still the placeholder text. Then stop the app with Control and C and start it again, because `.env` is only read at startup.

**Garmin says it is limiting requests.** Garmin blocks sign in and sync attempts that come too often. Wait about an hour and try again. Do not keep retrying, which can extend the wait.

**Garmin does not accept my login or code.** Check your email and password by signing in at connect.garmin.com. If you use two step verification, enter the newest code quickly because codes expire, and start over with Cancel if one fails. If it worked before and stopped, press Connect Garmin again to sign in fresh. As a fallback, run `venv/bin/python scripts/garmin_setup.py` from the project folder, or import `.fit` files by hand in Settings.

**The coach shows an error.** An invalid or revoked key shows an authentication error. Check the key in `.env` against the Anthropic console, fix it, and restart the app. Errors about credits or limits mean the Anthropic account needs more credit or has hit a spend limit. A rate limit or "overloaded" message usually clears up within a minute, so try again. Your message is not lost when a reply fails.

**The calendar is empty.** The calendar shows what is in your plan and your synced rides. If you have not connected Garmin or Strava yet, connect one in Settings, or import files by hand. If you have no planned workouts yet, ask the coach for a plan or add a workout from a day on the calendar. Also check that you are looking at the right month.

**My numbers differ a little from TrainingPeaks.** Training stress (TSS) is calculated by this app from your power or heart rate and your FTP or threshold heart rate, not copied from TrainingPeaks or Garmin. Small differences in FTP, in how normalized power is smoothed, and in the starting fitness value all change the totals. Set your real FTP and threshold heart rate in Settings, then press Recalculate TSS under Data tools. Setting Starting CTL to your fitness at the beginning of your history brings the fitness line closer to what you are used to.

**A ride shows up twice.** Press Remove Duplicates under Settings, Data tools. It keeps the version with more data.

## Under the hood

Python, Streamlit, SQLite, Plotly, and the Anthropic Claude API (`claude-opus-5-5` for chat, plans and race briefs, and the cheaper `claude-sonnet-5-5` at low effort for ride reviews and Garmin workout steps, set in `claude_client.py`). The app is built for one person per copy, so each athlete runs their own copy with their own `.env` and database.

```
app.py                    Entry point, setup and welcome gates, navigation
pages/                    Today, Plan, Dashboard, Data, Strength, Races, Competitors, Settings
planning.py               Training block generator used by Quick Generate
plan_changes.py           Moves, edits and removals of planned workouts, shared by the coach and the buttons
garmin_workouts.py        Turns workouts into Garmin steps and .fit files
claude_client.py          Claude calls, streaming, tool loop, error handling
coach_tools.py            Tools the coach can call over your data
coach_context.py          Coach persona and athlete snapshot
coach_reports.py          Ride review, weekly check in and race plan prompts
db/                       SQLite schema and queries
auth/                     Garmin and Strava sign in and sync, .fit and .csv import, ride data fetching
metrics/training_load.py  Fitness, fatigue and form (CTL, ATL, TSB)
metrics/plan_impact.py    What a change to the plan does to those numbers, plus plan warnings
metrics/zones.py          Power and heart rate zone estimates
metrics/analysis.py       Search filters, totals, weekly volume, efficiency, peak power curve, history and power profile
metrics/peaks.py          Best average power and heart rate by duration from a ride file
metrics/streams.py        Second by second ride data: smoothing, zones, efforts, pacing
metrics/explain.py        All the plain language wording, in one place
research/                 OBRA schedule and race results
components/               Shared interface pieces
components/calendar.py    Calendar data, moves and undo for the Plan page
components/calendar_dnd.py  The interactive grid (drag, click, hover)
components/plan_impact_ui.py  The Plan impact panel and undo bar
components/explain.py     Help icons and tooltips that explain a number in plain words
components/ftp_help.py    FTP estimate note, suggestion from best 20 minutes, guided test
components/ride_analysis.py  The ride analysis window
components/checklist.py   Getting started checklist on Today
components/data_filters.py  Date range, search and filters shared by Dashboard and Data
components/ride_detail.py   Rides table and ride detail used by Today and Data
components/history_table.py  The fitness history tables on the Dashboard
components/charts.py      Chart styling, drag to zoom and Reset zoom
scripts/garmin_setup.py   Terminal fallback for connecting Garmin
scripts/seed_demo_db.py   Builds a demo database
tests/                    Tests for the calendar, moves, plan impact, analysis, peaks, history and wording (python -m unittest discover -s tests)
.streamlit/config.toml    Dark theme
```

The coach can only read your data through a small set of read only tools. The one thing it can write, proposed workouts, takes effect only after you confirm in the app.

## License

MIT. See [LICENSE](LICENSE).
