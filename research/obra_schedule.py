from __future__ import annotations

"""
Fetch upcoming OBRA races from the official JSON API.
Endpoint: https://obra.org/schedule/{year}/{discipline}.json
Caches results in SQLite for 24 hours.
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

import requests
from db.schema import get_conn

OBRA_BASE = "https://obra.org"
HEADERS = {
    "User-Agent": "CyclingCoachApp/1.0 (personal training tool; not commercial)",
    "Accept": "application/json",
}
HEADERS_HTML = {**HEADERS, "Accept": "text/html"}

DISCIPLINES = {
    "Road": "road",
    "Criterium": "criterium",
    "Gravel": "gravel",
    "Time Trial": "time_trial",
    "Track": "track",
    "Mountain Bike": "mountain_bike",
}
# Reverse map: slug → display label used as category fallback
_SLUG_TO_LABEL = {v: k for k, v in DISCIPLINES.items()}


# ── Cache ─────────────────────────────────────────────────────────────────────

def _ensure_cache_table():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS obra_schedule_cache (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def _get_cache(key: str) -> list | None:
    _ensure_cache_table()
    conn = get_conn()
    row = conn.execute(
        "SELECT value, fetched_at FROM obra_schedule_cache WHERE key=?", (key,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    age = datetime.utcnow() - datetime.fromisoformat(row["fetched_at"])
    if age > timedelta(hours=24):
        return None
    return json.loads(row["value"])


def _set_cache(key: str, data: list):
    _ensure_cache_table()
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO obra_schedule_cache (key, value, fetched_at) VALUES (?,?,?)",
        (key, json.dumps(data), datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


# ── Fetch ─────────────────────────────────────────────────────────────────────

def _check_url(url: str) -> bool:
    """Return True if the URL responds with a non-error status code."""
    if not url:
        return False
    try:
        r = requests.head(url, timeout=6, allow_redirects=True,
                          headers={"User-Agent": HEADERS["User-Agent"]})
        return r.status_code < 400
    except Exception:
        return False


def _fetch_discipline(discipline_slug: str, year: int, include_past: bool = False) -> list[dict]:
    """Fetch one discipline's events from OBRA JSON API, with URL validation."""
    url = f"{OBRA_BASE}/schedule/{year}/{discipline_slug}.json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        time.sleep(0.3)
    except Exception:
        return []

    today = date.today().isoformat()
    category_label = _SLUG_TO_LABEL.get(discipline_slug, discipline_slug.replace("_", " ").title())

    raw = []
    for e in resp.json():
        event_date = e.get("start", "")
        if not include_past and event_date < today:
            continue
        raw.append({
            "id": e.get("id"),
            "name": e.get("title", "").strip(),
            "date": event_date,
            "url": e.get("url", ""),
            "discipline": discipline_slug,
            "category": category_label,
            "is_past": event_date < today,
        })

    # Validate URLs concurrently — drop events whose links are broken
    urls_to_check = [e["url"] for e in raw if e["url"]]
    url_ok: dict[str, bool] = {}
    if urls_to_check:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_check_url, u): u for u in set(urls_to_check)}
            for fut in as_completed(futures):
                url_ok[futures[fut]] = fut.result()

    events = []
    for e in raw:
        u = e["url"]
        # Keep event if it has no URL or if URL is reachable
        if not u or url_ok.get(u, True):
            events.append(e)
        else:
            e["url"] = ""  # clear broken URL but keep the event
            events.append(e)

    return sorted(events, key=lambda x: x["date"])


def get_upcoming_races(
    disciplines: list[str] | None = None,
    year: int | None = None,
    force_refresh: bool = False,
    include_past: bool = False,
) -> list[dict]:
    """
    Return OBRA races across selected disciplines.
    include_past=True returns the full year (past + upcoming).
    Cached for 24 hours per discipline.
    """
    if year is None:
        year = date.today().year
    if disciplines is None:
        disciplines = ["Road", "Criterium"]

    all_events = []
    for disc in disciplines:
        slug = DISCIPLINES.get(disc, disc.lower().replace(" ", "_"))
        # Separate cache keys for past-included vs upcoming-only
        cache_key = f"obra_{slug}_{year}{'_all' if include_past else ''}"

        cached = None if force_refresh else _get_cache(cache_key)
        if cached is not None:
            all_events.extend(cached)
        else:
            events = _fetch_discipline(slug, year, include_past=include_past)
            _set_cache(cache_key, events)
            all_events.extend(events)

    # Deduplicate by id, sort by date
    seen = set()
    unique = []
    for e in all_events:
        key = e.get("id") or (e["name"], e["date"])
        if key not in seen:
            seen.add(key)
            unique.append(e)

    return sorted(unique, key=lambda x: x["date"])


# ── Event detail scraper ──────────────────────────────────────────────────────

def _scrape_text_and_links(html: str) -> tuple[str, list[dict]]:
    """Strip HTML to plain text and extract all external links."""
    clean = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL)

    # Collect external links before stripping tags
    links = []
    for m in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*>([^<]{1,80})</a>',
                         clean, re.IGNORECASE):
        url, label = m.group(1).strip(), re.sub(r'\s+', ' ', m.group(2)).strip()
        if label and 'obra.org' not in url:
            links.append({"url": url, "label": label})

    text = re.sub(r'<[^>]+>', ' ', clean)
    text = re.sub(r'\s+', ' ', text).strip()
    return text, links


def _parse_distance(text: str) -> float | None:
    for pat, unit in [
        (r'\b(\d+(?:\.\d+)?)\s*km\b', 'km'),
        (r'\b(\d+(?:\.\d+)?)\s*miles?\b', 'mi'),
        (r'\b(\d+(?:\.\d+)?)\s*mi\b', 'mi'),
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            return val if unit == 'km' else round(val * 1.60934, 1)
    return None


def _parse_elevation(text: str) -> float | None:
    for pat in [
        r'(\d[\d,]+)\s*m(?:eters?)?\s*(?:of\s+)?(?:climbing|elevation|gain|ascent)',
        r'(?:climbing|elevation|gain|ascent)[^.]{0,40}?(\d[\d,]+)\s*m(?:eters?)?(?!\w)',
        r'(\d[\d,]+)\s*(?:ft|feet)\s*(?:of\s+)?(?:climbing|elevation|gain|ascent)',
        r'(?:climbing|elevation|gain|ascent)[^.]{0,40}?(\d[\d,]+)\s*(?:ft|feet)',
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(',', '')
            val = float(raw)
            if 'ft' in m.group(0).lower() or 'feet' in m.group(0).lower():
                val = round(val * 0.3048)
            return round(val)
    return None


def _scrape_external_site(url: str) -> dict:
    """Fetch an external race website and pull whatever details we can find."""
    try:
        resp = requests.get(url, headers=HEADERS_HTML, timeout=12)
        resp.raise_for_status()
        time.sleep(0.4)
        html = resp.text
    except Exception:
        return {}

    text, _ = _scrape_text_and_links(html)
    details: dict = {}

    dist = _parse_distance(text)
    if dist:
        details["distance_km"] = dist

    elev = _parse_elevation(text)
    if elev:
        details["elevation_m"] = elev

    # Start time
    m = re.search(r'\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))', text)
    if m:
        details["start_time"] = m.group(1)

    # Course description — grab the longest sentence mentioning "course", "lap", "circuit", "climb"
    sentences = re.split(r'(?<=[.!?])\s+', text)
    course_sentences = [
        s.strip() for s in sentences
        if re.search(r'course|lap|circuit|climb|descent|finish|start|loop', s, re.IGNORECASE)
        and 20 < len(s) < 400
    ]
    if course_sentences:
        details["course_description"] = ' '.join(course_sentences[:3])

    # Registration link
    for m in re.finditer(r'(https?://(?:www\.)?bikereg\.com/\S+)', text, re.IGNORECASE):
        details["registration_url"] = m.group(1).rstrip('.,)')
        break

    return details


def get_event_details(event_id: int) -> dict:
    """
    Scrape the OBRA event page, then follow any external race website listed,
    and return everything found: distance_km, elevation_m, start_time,
    location, promoter, website_url, registration_url, course_description,
    external_links.
    Cached for 7 days.
    """
    cache_key = f"obra_event_detail2_{event_id}"
    cached = _get_cache(cache_key)
    if cached is not None:
        return cached[0] if cached else {}

    try:
        resp = requests.get(f"{OBRA_BASE}/events/{event_id}",
                            headers=HEADERS_HTML, timeout=15)
        resp.raise_for_status()
        time.sleep(0.3)
        html = resp.text
    except Exception:
        _set_cache(cache_key, [{}])
        return {}

    text, ext_links = _scrape_text_and_links(html)
    details: dict = {}

    # ── Distance & elevation from OBRA page ───────────────────────────────────
    dist = _parse_distance(text)
    if dist:
        details["distance_km"] = dist

    elev = _parse_elevation(text)
    if elev:
        details["elevation_m"] = elev

    # ── Start time ────────────────────────────────────────────────────────────
    m = re.search(r'\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))', text)
    if m:
        details["start_time"] = m.group(1)

    # ── Location / venue ──────────────────────────────────────────────────────
    for pat in [r'(?:location|venue|start|held at)[:\s]+([A-Z][^.]{5,60})',
                r'([A-Z][a-z]+(?: [A-Z][a-z]+)*, Oregon)',
                r'([A-Z][a-z]+(?: [A-Z][a-z]+)*, OR\b)']:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip().rstrip(',')
            if len(candidate) < 80:
                details["location"] = candidate
                break

    # ── Promoter ──────────────────────────────────────────────────────────────
    m = re.search(r'(?:promoter|promoted by|organizer)[:\s]+([A-Z][^.\n]{3,60})', text, re.IGNORECASE)
    if m:
        details["promoter"] = m.group(1).strip()

    # ── Course description ────────────────────────────────────────────────────
    sentences = re.split(r'(?<=[.!?])\s+', text)
    course_sents = [
        s.strip() for s in sentences
        if re.search(r'course|lap|circuit|climb|descent|finish|start|loop|rolling|flat|hilly',
                     s, re.IGNORECASE)
        and 20 < len(s) < 400
    ]
    if course_sents:
        details["course_description"] = ' '.join(course_sents[:3])

    # ── External links from OBRA page ─────────────────────────────────────────
    # Filter to useful links (skip social media, sponsors), then validate
    useful = [
        lnk for lnk in ext_links
        if not re.search(r'facebook|twitter|instagram|youtube|paypal|google|apple', lnk["url"], re.I)
    ]
    if useful:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(_check_url, lnk["url"]): lnk for lnk in useful[:8]}
            live = [futures[fut] for fut in as_completed(futures) if fut.result()]
        live = live[:6]
        if live:
            details["external_links"] = live
            details["website_url"] = live[0]["url"]

    # ── Registration link ─────────────────────────────────────────────────────
    for lnk in ext_links:
        if 'bikereg.com' in lnk["url"] or 'crossreg' in lnk["url"] or 'active.com' in lnk["url"]:
            details["registration_url"] = lnk["url"]
            break

    # ── Follow external race website for more details ─────────────────────────
    website = details.get("website_url")
    if website and not details.get("course_description"):
        ext = _scrape_external_site(website)
        for key, val in ext.items():
            details.setdefault(key, val)  # OBRA page takes priority

    _set_cache(cache_key, [details])
    return details
