"""
Single source of truth for the app's colors. styles.py writes these into the
CSS variables, and charts.py and the calendar read the same values, so a
color changed here changes everywhere.
"""

BG = "#0F1117"
SURFACE = "#1A1D2B"
RAISED = "#22263A"
BORDER = "#2A2F45"

TEXT1 = "#EEF2F8"
TEXT2 = "#B4BFD6"
TEXT3 = "#8A95AE"

ACCENT = "#4D9FFF"
FITNESS = "#4D9FFF"
FATIGUE = "#FF8A4C"
GOOD = "#34D399"
WARN = "#FBBF24"
BAD = "#F87171"
STRENGTH = "#C084FC"
RACE = "#F472B6"

# Power zones 1 to 5, tuned to read on the dark surface.
ZONE_COLORS = ["#8AB4F8", "#34D399", "#FBBF24", "#FB923C", "#F87171"]
ZONE_LABELS = ["Z1", "Z2", "Z3", "Z4", "Z5"]

# Calendar day states.
STATUS_COLORS = {
    "done": GOOD,
    "short": WARN,
    "missed": BAD,
    "planned": ACCENT,
    "extra": "#2DD4BF",
    "rest": BORDER,
}
STATUS_LABELS = {
    "done": "Done",
    "short": "Short of plan",
    "missed": "Missed",
    "planned": "Planned",
    "extra": "Unplanned ride",
    "rest": "Rest",
}

FONT_STACK = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
GRID = "rgba(154,166,191,0.18)"
