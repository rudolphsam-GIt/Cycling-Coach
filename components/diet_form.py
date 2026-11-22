"""
The "How you eat" questions, drawn the same way in onboarding, Settings and Add athlete.
render() draws the widgets and returns the answers in metrics.diet's shape. The caller saves them
with metrics.diet.save, so each page keeps its own save button and flow.
"""
from __future__ import annotations

import streamlit as st

from metrics import diet

HELP = {
    "diet": "Food ideas and recipes only show what fits. You can change it any time.",
    "avoid": ("Anything here is never shown, in a food, a recipe or a coach reply. Foods whose labels say "
              "they may contain it are hidden too, and so are foods whose allergens haven't been checked."),
    "gut": "Favours low fibre, low fat foods before and during rides, which sit easier on the stomach.",
    "referral": ("If yes, fuel targets come with a note to check with a doctor or registered sports "
                 "dietitian, and the app never adjusts them for you."),
    "height": "Optional. With age and the sex question below it gives a rough calorie estimate.",
    "energy_sex": ("Optional, and separate from gender. The calorie formula has a female and a male version. "
                   "Prefer not to say shows a range that covers both."),
    "ride_time": "When you usually ride, for pre ride meal timing when a workout has no start time.",
    "cooking": "Used to rank recipes, so quick days get quick meals.",
    "notes": "Anything else about how you eat. Only the coach reads this. It never filters foods by itself.",
}


def _index(options: dict, value) -> int | None:
    values = list(options.values())
    return values.index(value) if value in values else None


def _yes_no(label: str, value, key: str, help: str) -> bool | None:
    choice = st.radio(label, ["Yes", "No"], index=None if value is None else (0 if value else 1),
                      key=key, horizontal=True, help=help)
    return None if choice is None else choice == "Yes"


def height_input(cm, *, key: str, unit: str, label: str = "Height") -> float | None:
    """Feet and inches for riders who use pounds, else cm. Optional, so it can stay empty."""
    if unit == "lb":
        ft_in = diet.ft_in_from_cm(cm)
        c1, c2 = st.columns(2)
        feet = c1.number_input(f"{label} (ft)", min_value=3, max_value=7, step=1, key=f"{key}_ft",
                               value=ft_in[0] if ft_in else None, placeholder="Optional", help=HELP["height"])
        inches = c2.number_input(f"{label} (in)", min_value=0, max_value=11, step=1, key=f"{key}_in",
                                 value=ft_in[1] if ft_in else None, placeholder="Optional")
        return diet.cm_from_ft_in(feet, inches) if feet else None
    c1, _ = st.columns(2)
    shown = c1.number_input(f"{label} (cm)", min_value=diet.HEIGHT_CM_MIN, max_value=diet.HEIGHT_CM_MAX,
                            step=1, key=f"{key}_cm", value=int(round(cm)) if cm else None,
                            placeholder="Optional", help=HELP["height"])
    return float(shown) if shown else None


def render(*, key: str, unit: str, saved: dict | None = None, whose: str = "you") -> dict:
    """Draw the questions. whose is "you" or "they" for the coach's Add athlete form."""
    saved = saved or {}
    you = whose == "you"
    q = (lambda mine, theirs: mine if you else theirs)

    diet_label = st.selectbox(q("How do you eat?", "How do they eat?"), list(diet.DIETS),
                              index=_index(diet.DIETS, saved.get("diet")) or 0, key=f"{key}_diet",
                              help=HELP["diet"])
    avoid = st.multiselect(q("Foods you avoid", "Foods they avoid"), list(diet.AVOID),
                           default=diet.avoid_labels(saved.get("avoid_foods")), key=f"{key}_avoid",
                           placeholder="None", help=HELP["avoid"])
    gut = _yes_no(q("Does your stomach get upset on rides?", "Does their stomach get upset on rides?"),
                  saved.get("gut_sensitive"), f"{key}_gut", HELP["gut"])
    referral = _yes_no(q(diet.REFERRAL_QUESTION, diet.REFERRAL_QUESTION_THEY),
                       saved.get("nutrition_referral"), f"{key}_referral", HELP["referral"])
    if referral:
        st.info(q(diet.REFERRAL_MESSAGE, diet.REFERRAL_MESSAGE_THEY), icon=":material/health_and_safety:")

    height = height_input(saved.get("height_cm"), key=f"{key}_height", unit=unit)
    s_col, t_col = st.columns(2)
    sex_label = s_col.selectbox("Sex for energy estimates", list(diet.ENERGY_SEX),
                                index=_index(diet.ENERGY_SEX, saved.get("energy_sex")),
                                placeholder="Optional", key=f"{key}_energy_sex", help=HELP["energy_sex"])
    ride_label = t_col.selectbox(q("When do you usually ride?", "When do they usually ride?"),
                                 list(diet.RIDE_TIMES), index=_index(diet.RIDE_TIMES, saved.get("usual_ride_time")),
                                 placeholder="Optional", key=f"{key}_ride_time", help=HELP["ride_time"])
    cook_label = st.selectbox("Cooking", list(diet.COOKING),
                              index=_index(diet.COOKING, saved.get("cooking_time")),
                              placeholder="Optional", key=f"{key}_cooking", help=HELP["cooking"])
    notes = st.text_area(q("Anything else about how you eat?", "Anything else about how they eat?"),
                         value=saved.get("diet_notes", ""), key=f"{key}_notes", height=70,
                         placeholder="For example no pork, or lactose is fine in small amounts",
                         help=HELP["notes"])
    return {
        "diet": diet.DIETS[diet_label],
        "avoid_foods": [diet.AVOID[a] for a in avoid],
        "gut_sensitive": gut,
        "nutrition_referral": referral,
        "height_cm": height,
        "energy_sex": diet.ENERGY_SEX.get(sex_label),
        "usual_ride_time": diet.RIDE_TIMES.get(ride_label),
        "cooking_time": diet.COOKING.get(cook_label),
        "diet_notes": notes,
    }
