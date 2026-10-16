# Training research library

The AI Coach reads these files before it plans, so its advice rests on published sports science instead of general knowledge. Researched and written 2026-10-10.

## How the coach uses it

- `principles.md` is a short distilled list that is added to every coach system prompt, so the core rules are always in force.
- Each topic file can be pulled in full through the `get_training_research` tool (up to 3 topics per call). The coach is told to read the right topics before building a block, program or weekly plan, and when the athlete asks why.
- `knowledge.py` loads the files. The tool's topic list is built from the files present, so a new topic is just a new file with the same layout.

## Topics

| Topic key | What it covers | References |
|---|---|---|
| `intensity_distribution` | Polarized, pyramidal, threshold and sweet spot training | 34 |
| `intervals` | VO2max (30/15, 4x8, 5x4), threshold, sweet spot and sprint intervals, dose and progression | 36 |
| `periodization_taper` | Traditional, block and reverse periodization, tapering, off season and detraining | 40 |
| `weekly_structure` | Sessions per week, spacing hard days, the long ride, templates for 3 to 6 riding days | 32 |
| `time_available` | What works at 3, 5, 8, 12 and 15+ hours a week, maintenance in busy spells | 37 |
| `age` | Masters riders by decade, recovery, VO2max decline, bone, protein, heart safety, juniors | 58 |
| `women` | Sex differences, menstrual cycle, contraception, pregnancy, menopause, REDs, iron | 47 |
| `recovery_load` | Sleep, overreaching, CTL/ATL/TSB, ramp rates, HRV, wellness checks, recovery methods | 40 |
| `strength` | Heavy and explosive lifting for cyclists, concurrent training, in season maintenance, bone | 44 |
| `testing` | 20 minute and ramp tests, critical power, retest timing, LTHR, zone systems | 44 |
| `nutrition` | Daily carbohydrate, fueling per ride, protein, hydration, train low, caffeine, nitrate | 53 |
| `environment` | Heat acclimation, cold, altitude, hypoxic tents, air quality and wildfire smoke | 52 |
| `cross_training` | Running, Nordic and skate skiing, ski touring, downhill skiing, hockey, swimming and other sports; transfer to cycling, sport specific hrTSS, injury and safety | 26 |

543 references in total. Revised 2026-10-11 to widen the evidence pool: every finding now states how many studies and people it rests on. The cross_training topic was added 2026-10-16.

## File layout

Every topic file has the same parts, and `tests/test_knowledge.py` checks them.

1. Front matter with `topic`, `title`, `keywords` and `last_reviewed`.
2. **Summary** in plain words.
3. **Size of the evidence**, how big the pool is for the topic overall, the largest datasets, and where it is still small.
4. **Key findings**, each graded **Strong**, **Moderate** or **Limited**, with a **Pool** line (number of studies and people, and who they were) and, where it exists, a **Real world data** line for large observational datasets.
5. **Rules for the coach**, concrete numbers the app can act on. Rules that are coaching convention rather than research say so.
6. **Where evidence is thin or disputed**.
7. **References** with authors, year, journal and a DOI or PubMed link.

## How it was checked

Grades follow pool size. Strong needs pooled evidence from several hundred or more people across independent groups with consistent results. Large observational datasets (for example training logs of 119,452 marathoners, race results of over 800,000 triathletes, wearable data from thousands of users) are reported but never raise a grade on their own, since they show associations rather than cause and effect. Most of the large real world data comes from runners; no large peer reviewed analysis of amateur cyclists' platform data (Strava, TrainingPeaks, Zwift, Garmin, intervals.icu) was found, and the files say so.


Each topic was researched from abstracts and full texts of systematic reviews, meta analyses, consensus statements and trials, preferring studies in cyclists or trained endurance athletes. Findings from runners, untrained people or small samples are labelled as such. Every DOI in the library was then looked up on Crossref to confirm it exists and matches the cited title. A few sources have no DOI (a TrainingPeaks article, the TrainerRoad ramp test FAQ, EPA air quality pages, a news report on junior gearing, a postnatal running guideline); each is labelled in its file as not peer reviewed where that applies.

## Keeping it current

Set `last_reviewed` when a file is revised. Good times to revisit are a new major meta analysis or consensus statement (for example an IOC or ACSM update) or when a rule in the file disagrees with what riders in the app actually show.
