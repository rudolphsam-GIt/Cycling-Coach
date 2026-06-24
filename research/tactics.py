"""
Generate a race tactics brief using Claude, given competitor profiles and race info.
"""

import anthropic
from config import ANTHROPIC_API_KEY
from db.queries import get_setting
from metrics.training_load import get_current_metrics


TACTICS_SYSTEM = """You are an expert road cycling race tactician and coach.
Your job is to analyze competitor data from OBRA race results and produce
a specific, actionable race tactics brief for your athlete.

Be direct and specific. Name competitors by name when discussing tactics.
Focus on: positioning, when to cover moves, who to mark, pacing strategy,
and how to use your athlete's strengths against the field's weaknesses.

Use only the data provided — don't invent facts about competitors."""


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

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

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
6. **Wildcard** — one thing that could change the race"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=[
                {
                    "type": "text",
                    "text": TACTICS_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as e:
        return f"Error generating tactics: {e}"
