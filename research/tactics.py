"""
Generate a race tactics brief using Claude, given competitor profiles and race info.
"""

import claude_client
from config import ANTHROPIC_API_KEY
from db.queries import get_setting
from metrics.training_load import get_current_metrics


TACTICS_SYSTEM = """You are an expert road cycling race tactician and coach.
Your job is to analyze competitor data from OBRA race results and produce
a specific, actionable race tactics brief for your athlete.

Be direct and specific. Name competitors by name when discussing tactics.
Focus on: positioning, when to cover moves, who to mark, pacing strategy,
and how to use your athlete's strengths against the field's weaknesses.

Use only the data provided — don't invent facts about competitors.

Evidence rules:
- Back every claim about a competitor with the specific OBRA result it comes from, written
  inline in brackets, for example [Mt Tabor Series, 3rd of 42, Cat 3].
- If a rider has few or no results, say the read on them is thin rather than guessing.
- Keep your athlete's strengths grounded in the FTP, W/kg, CTL and TSB given.
- End with a short "Confidence" line: High, Medium or Low, and why, based on how much
  result data the field has."""


def build_competitor_summary(profiles: list[dict]) -> str:
    lines = []
    for p in profiles:
        name = p.get("name") or p.get("search_name", "Unknown")
        if p.get("error"):
            lines.append(f"- {name}: No OBRA data found")
            continue

        cat = f"Cat {p['road_category']}" if p.get("road_category") else "Category unknown"
        team = p.get("team") or "No team"
        loc = p.get("location") or ""
        url = p.get("profile_url", "")

        recent = p.get("recent_results", [])
        results_str = "; ".join(recent[:5]) if recent else "No recent results"

        lines.append(
            f"- {name} | {cat} | {team} | {loc}\n"
            f"  Recent results: {results_str}\n"
            f"  Profile: {url}"
        )
    return "\n".join(lines)


def generate_tactics_brief(
    race_name: str,
    race_distance_km: float,
    race_elevation_m: float,
    race_notes: str,
    competitor_profiles: list[dict],
) -> str:
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "paste_your_key_here":
        return "Claude API key not configured. Add ANTHROPIC_API_KEY to your .env file."

    ftp = get_setting("ftp_watts", "unknown")
    weight = get_setting("weight_kg", "unknown")
    metrics = get_current_metrics()

    try:
        w_per_kg = round(float(ftp) / float(weight), 2)
    except Exception:
        w_per_kg = "unknown"

    competitor_summary = build_competitor_summary(competitor_profiles)
    found_count = sum(1 for p in competitor_profiles if not p.get("error"))
    total_count = len(competitor_profiles)

    prompt = f"""Generate a race tactics brief for my athlete racing in {race_name}.

RACE DETAILS:
- Distance: {race_distance_km} km
- Elevation: {race_elevation_m} m
- Notes: {race_notes or "None provided"}

MY ATHLETE:
- FTP: {ftp}W | Weight: {weight}kg | W/kg: {w_per_kg}
- CTL (fitness): {metrics['ctl']:.1f} | TSB (form): {metrics['tsb']:.1f}

COMPETITORS ({found_count} of {total_count} found on OBRA):
{competitor_summary}

Please provide:
1. **Field Assessment** — strength of the field, key threats
2. **Who to Mark** — 2-3 specific riders to watch, and why
3. **Race Strategy** — start positioning, when to cover moves, when to attack
4. **When to Go** — specific race scenario triggers (e.g., "if X attacks on the climb, cover immediately")
5. **Pacing Plan** — how to manage effort given the field
6. **Wildcard** — one thing that could change the race
7. **Confidence** — how much to trust this brief given the data available"""

    # Tactics call for real reasoning about the field, so use high effort.
    return claude_client.ask(
        [{"type": "text", "text": TACTICS_SYSTEM}],
        [{"role": "user", "content": prompt}],
        effort="high",
    )
