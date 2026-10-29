"""
The Google Form a new athlete fills in before Sam coaches them. The questions live here, and
apps_script() turns them into a Google Apps Script that builds the form and its response sheet.
The importer reads the sheet back by question title, so the form and the importer share this one
list. Questions that feed the Add athlete form use the app's own choices, word for word.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import planning
from components.onboarding import GOAL_EXAMPLES
from metrics.explain import ACTIVITY_DETAILS, ACTIVITY_LEVEL, GENDER_LABELS, RIDER_TYPES

FORM_TITLE = "Cycling coaching intake"
FORM_DESCRIPTION = (
    "A few questions so I can build a training plan that fits you. It takes about 10 minutes. "
    "Skip anything you don't know.\n\n"
    "Your answers go into my coaching app, which uses an AI assistant to help me plan your training. "
    "I review every plan before you get it.")
CONFIRMATION = "Thanks. I'll be in touch soon with your first weeks of training."

# Full day names on the form. planning.parse_days reads the first three letters, so they import as is.
DAY_NAMES = {"Monday": "Mon", "Tuesday": "Tue", "Wednesday": "Wed", "Thursday": "Thu",
             "Friday": "Fri", "Saturday": "Sat", "Sunday": "Sun"}
assert tuple(DAY_NAMES.values()) == planning.WEEKDAYS

# One question sets both units, since riders think in one system.
UNIT_CHOICES = {"Pounds and miles": ("lb", "mi"), "Kilograms and kilometers": ("kg", "km")}

# The rider's FTP test answer, as the Add athlete form's FTP choice (athlete_form.FTP_CHOICES).
# None leaves it for Sam to pick when reviewing the import.
FTP_TEST_CHOICES = {
    "Yes, include a test": "test",
    "No, use the FTP I gave above": "known",
    "No, estimate it from my rides": "estimate",
    "Not sure, you decide": None,
}

RIDE_SHARE_HELP = (
    "Your past rides let me see your real fitness instead of guessing. The last 3 months is ideal, "
    "and 6 weeks is enough to start. I can use .fit files, .fit.gz files, or a .zip of either.\n\n"
    "Strava (easiest). On the website go to Settings, then My Account, then Download or Delete Your "
    "Account, and request your archive. Strava emails you a zip. Send me the whole zip.\n\n"
    "Garmin Connect. Open a ride, click the gear icon, and choose Export Original. Do this for each "
    "ride. To send everything at once, request a data export at garmin.com/account/datamanagement. "
    "It can take a day or two to arrive.\n\n"
    "Zwift, Wahoo or another app. Most can export .fit files. Put them in a zip and send it over.")


@dataclass(frozen=True)
class Question:
    key: str                         # what the importer calls this answer
    title: str                       # the question text, and the response sheet's column name
    kind: str                        # text, email, number, paragraph, choice, checkbox, list or date
    choices: tuple[str, ...] = ()
    help: str = ""
    required: bool = False
    bounds: tuple[int, int] | None = None     # number questions only


@dataclass(frozen=True)
class Section:
    title: str
    description: str
    questions: tuple[Question, ...]


def _details(options: dict[str, str]) -> str:
    return "\n".join(f"{name}. {detail}" for name, detail in options.items())


YES_NO = ("Yes", "No")

SECTIONS = (
    Section("About you", "", (
        Question("name", "Your name", "text", required=True),
        Question("email", "Your email", "email", required=True, help="So I can send you your plan."),
        Question("age", "Your age", "number", bounds=(12, 95)),
        Question("gender", "Gender", "list", tuple(GENDER_LABELS),
                 help="Only used to pick a typical starting power range."),
        Question("units", "Which units do you use?", "choice", tuple(UNIT_CHOICES), required=True),
        Question("weight", "Your weight", "number", bounds=(30, 450),
                 help="In the units you picked above."),
    )),
    Section("Your riding", "", (
        Question("rider_type", "Which best describes you?", "choice", tuple(RIDER_TYPES), required=True,
                 help=_details({k: v["detail"] for k, v in RIDER_TYPES.items()})),
        Question("activity", "How active are you right now?", "choice", tuple(ACTIVITY_LEVEL),
                 required=True, help=_details(ACTIVITY_DETAILS)),
        Question("years_riding", "How long have you been riding?", "choice",
                 ("Less than a year", "1 to 3 years", "3 to 10 years", "More than 10 years")),
        Question("longest_ride", "Your longest ride in the last two months", "text",
                 help="Distance or time, whichever you know."),
    )),
    Section("Your goals", "", (
        Question("goal_text", "What is your main goal?", "paragraph", required=True,
                 help="In your own words. A sentence or two is plenty. For example "
                      + ", ".join(GOAL_EXAMPLES).lower() + "."),
        Question("success", "What would make the next 3 to 6 months a success?", "paragraph"),
        Question("race_name", "Are you training for an event? What is it called?", "text"),
        Question("race_date", "Event date", "date"),
        Question("event_type", "What kind of event is it?", "choice",
                 ("Road race", "Criterium", "Gravel race", "Gran fondo or sportive",
                  "Century or other long ride", "Time trial", "Mountain bike race", "Multi day tour",
                  "Something else")),
        Question("event_details", "Event distance and climbing", "text",
                 help="Whatever you know, for example 70 miles with 5,000 feet of climbing."),
        Question("event_aim", "What do you want from the event?", "choice",
                 ("Finish comfortably", "Set a personal best", "Race for a result",
                  "Enjoy the day with friends")),
    )),
    Section("Your time", "", (
        Question("weekly_hours", "How many hours a week can you train?", "number", required=True,
                 bounds=(1, 20)),
        Question("available_days", "Which days can you ride?", "checkbox", tuple(DAY_NAMES),
                 required=True),
        Question("long_ride_day", "Best day for a longer ride", "choice",
                 tuple(DAY_NAMES) + ("No preference",)),
        Question("weekday_time", "How much time do you have for a weekday ride?", "choice",
                 ("Under 45 minutes", "45 to 60 minutes", "60 to 90 minutes", "More than 90 minutes")),
        Question("plan_start", "When would you like your plan to start?", "date"),
        Question("plan_end", "When would you like your plan to end?", "date",
                 help="Often the day of your event. Plans run from 2 weeks to about a year. "
                      "Leave it blank and I'll suggest a length."),
    )),
    Section("Your numbers", "All optional. Skip anything you don't know and I'll work it out from your rides.", (
        Question("ftp_input", "FTP in watts", "number", bounds=(50, 600)),
        Question("ftp_source", "How and when did you get that FTP?", "text",
                 help="For example a 20 minute test in Zwift last month."),
        Question("ftp_test", "Would you like an FTP test in your first weeks?", "choice",
                 tuple(FTP_TEST_CHOICES),
                 help="An FTP test is one hard effort, usually 20 minutes or a ramp test on a trainer. "
                      "It sets your training zones. It helps most if you don't know your FTP or it's "
                      "more than a couple of months old."),
        Question("lthr_input", "Threshold heart rate", "number", bounds=(80, 220),
                 help="The heart rate you can hold for about an hour."),
        Question("max_hr", "Max heart rate", "number", bounds=(100, 230)),
        Question("resting_hr", "Resting heart rate", "number", bounds=(30, 120)),
        Question("current_ctl", "Fitness (CTL) from TrainingPeaks or intervals.icu", "number",
                 bounds=(0, 200),
                 help="Not the Fitness number in Strava, which uses its own scale."),
    )),
    Section("Your gear", "", (
        Question("equipment", "What do you have?", "checkbox",
                 ("Power meter", "Heart rate strap or watch", "Smart trainer",
                  "Basic indoor trainer or rollers", "Bike computer (Garmin, Wahoo, Hammerhead)",
                  "None of these")),
        Question("apps", "Which apps do you use?", "checkbox",
                 ("Strava", "Garmin Connect", "TrainingPeaks", "intervals.icu", "Zwift", "Something else")),
    )),
    Section("How you like to train", "", (
        Question("indoor_outdoor", "Indoors or outdoors?", "choice",
                 ("Mostly outdoors", "Mostly indoors", "A mix", "No preference")),
        Question("group_rides", "Any regular group rides? Which day, and what are they like?", "paragraph"),
        Question("strength", "Would you like strength training in your plan?", "choice",
                 ("Yes, I'd like some", "I already do some", "Not right now")),
        Question("enjoy", "What do you enjoy about riding?", "paragraph"),
        Question("dislike", "Anything you'd rather avoid?", "paragraph"),
        Question("past_training", "What has worked, or not worked, for you before?", "paragraph"),
    )),
    Section("Your ride history", "", (
        Question("ride_share", "How can you share your ride history?", "choice",
                 ("I'll send a Strava export", "I'll send a Garmin export or .fit files",
                  "I'll share a Drive or Dropbox folder", "I don't track my rides", "I'm not sure how"),
                 help=RIDE_SHARE_HELP),
    )),
    Section("Health and safety", "This keeps your training safe. Only your coach sees these answers.", (
        Question("doctor_limit", "Has a doctor ever told you to limit exercise, or that you have a heart condition?",
                 "choice", YES_NO, required=True),
        Question("warning_signs", "Do you ever get chest pain, fainting, dizziness or a racing heartbeat when you exercise?",
                 "choice", YES_NO, required=True),
        Question("injuries", "Any injuries or pain right now?", "paragraph"),
        Question("conditions", "Any medical conditions or limits from a doctor I should know about?", "paragraph",
                 help="For example asthma, diabetes, high blood pressure, osteoporosis, pregnancy or a recent birth."),
        Question("hr_meds", "Do you take any medicine that changes your heart rate, such as beta blockers?",
                 "choice", YES_NO + ("Not sure",), required=True),
        Question("consent", "Please confirm", "checkbox",
                 ("I understand this is training advice, not medical advice, and I'll check with a doctor "
                  "if I'm unsure about exercising.",), required=True),
    )),
    Section("Anything else", "", (
        Question("notes", "Anything else I should know?", "paragraph"),
    )),
)

QUESTIONS = tuple(q for s in SECTIONS for q in s.questions)


def _question_json(q: Question) -> dict:
    d = {"title": q.title, "kind": q.kind, "required": q.required}
    if q.choices:
        d["choices"] = list(q.choices)
    if q.help:
        d["help"] = q.help
    if q.bounds:
        d["min"], d["max"] = q.bounds
    return d


_SCRIPT = """\
// Builds the cycling coaching intake form and its response sheet.
// Made by scripts/make_intake_form.py. Change the questions in intake_form.py, not here.
// Paste into a new project at script.google.com, pick createIntakeForm and press Run.
// The links show in the execution log when it finishes.

const FORM = %s;

function createIntakeForm() {
  const form = FormApp.create(FORM.title);
  form.setDescription(FORM.description);
  form.setConfirmationMessage(FORM.confirmation);
  form.setProgressBar(true);
  FORM.sections.forEach(function (section, i) {
    // A page per section, so the form doesn't feel like one long wall of questions.
    const header = i === 0 ? form.addSectionHeaderItem() : form.addPageBreakItem();
    header.setTitle(section.title);
    if (section.description) header.setHelpText(section.description);
    section.questions.forEach(function (q) { addQuestion(form, q); });
  });
  const sheet = SpreadsheetApp.create(FORM.title + " responses");
  form.setDestination(FormApp.DestinationType.SPREADSHEET, sheet.getId());
  Logger.log("Send riders this link: " + form.getPublishedUrl());
  Logger.log("Edit the form: " + form.getEditUrl());
  Logger.log("Responses: " + sheet.getUrl());
}

function addQuestion(form, q) {
  let item;
  if (q.kind === "paragraph") item = form.addParagraphTextItem();
  else if (q.kind === "date") item = form.addDateItem();
  else if (q.kind === "choice") item = form.addMultipleChoiceItem().setChoiceValues(q.choices);
  else if (q.kind === "checkbox") item = form.addCheckboxItem().setChoiceValues(q.choices);
  else if (q.kind === "list") item = form.addListItem().setChoiceValues(q.choices);
  else {
    item = form.addTextItem();
    if (q.kind === "email") {
      item.setValidation(FormApp.createTextValidation()
        .setHelpText("Please enter an email address.").requireTextIsEmail().build());
    } else if (q.kind === "number") {
      item.setValidation(FormApp.createTextValidation()
        .setHelpText("Please enter a number from " + q.min + " to " + q.max + ".")
        .requireNumberBetween(q.min, q.max).build());
    }
  }
  item.setTitle(q.title).setRequired(q.required);
  if (q.help) item.setHelpText(q.help);
}
"""


def apps_script() -> str:
    """The Apps Script that builds the form, with the questions baked in as JSON."""
    form = {
        "title": FORM_TITLE, "description": FORM_DESCRIPTION, "confirmation": CONFIRMATION,
        "sections": [{"title": s.title, "description": s.description,
                      "questions": [_question_json(q) for q in s.questions]} for s in SECTIONS],
    }
    return _SCRIPT % json.dumps(form, indent=2, ensure_ascii=False)
