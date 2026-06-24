from __future__ import annotations

"""
OBRA public results scraper.

Respects robots.txt (only discobot is blocked, no User-agent: * rule).
Uses 0.5s delays between requests and identifies itself via User-Agent.
Only reads publicly visible pages — no login, no private data.
"""

import time
import re
import sqlite3
import json
from datetime import date, timedelta
from html.parser import HTMLParser

import requests

OBRA_BASE = "https://obra.org"
HEADERS = {
    "User-Agent": "CyclingCoachApp/1.0 (personal training tool; not commercial)",
    "Accept": "text/html",
}
REQUEST_DELAY = 0.5  # seconds between requests — be a good citizen


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get(path: str, retries: int = 2) -> requests.Response | None:
    url = f"{OBRA_BASE}{path}" if path.startswith("/") else path
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            time.sleep(REQUEST_DELAY)
            return resp
        except requests.HTTPError as e:
            if e.response.status_code in (404, 410):
                return None
            time.sleep(1)
        except Exception:
            time.sleep(1)
    return None


def _text(resp) -> str:
    return resp.text if resp else ""


# ── Event list ────────────────────────────────────────────────────────────────

def get_recent_event_ids(year: int = None, limit: int = 30) -> list[dict]:
    """
    Fetch the OBRA results index and return recent road/crit event IDs.
    Returns [{id, name, url}]
    """
    if year is None:
        year = date.today().year

    resp = _get(f"/results?year={year}")
    html = _text(resp)
    if not html:
        return []

    # Find links matching /events/DIGITS/results
    pattern = r'href="(/events/(\d+)/results)"[^>]*>([^<]+)</a>'
    matches = re.findall(pattern, html)

    events = []
    for path, eid, name in matches:
        name = name.strip()
        # Filter for road/crit type events (skip MTB, CX, TT if desired)
        events.append({"id": int(eid), "name": name, "path": path})

    # Also try previous year if we don't have many events yet
    if len(events) < 5 and year == date.today().year:
        resp2 = _get(f"/results?year={year - 1}")
        html2 = _text(resp2)
        for path, eid, name in re.findall(pattern, html2):
            events.append({"id": int(eid), "name": name.strip(), "path": path})

    return events[:limit]


# ── Search for a rider across recent events ──────────────────────────────────

def find_rider_in_results(name: str, event_ids: list[dict]) -> dict | None:
    """
    Search through recent OBRA event result pages looking for a rider by name.
    Returns {people_id, name, found_in_event} or None.
    Case-insensitive partial match on last name + first name.
    """
    name_lower = name.strip().lower()
    name_parts = name_lower.split()

    for event in event_ids:
        resp = _get(event["path"])
        html = _text(resp)
        if not html:
            continue

        # Find all rider links: href="/people/DIGITS/YEAR">Name</a>
        pattern = r'href="(/people/(\d+)/\d+)"[^>]*>([^<]+)</a>'
        for path, pid, rider_name in re.findall(pattern, html):
            rn_lower = rider_name.strip().lower()
            # Match if all name parts appear in the rider name
            if all(part in rn_lower for part in name_parts):
                return {
                    "people_id": int(pid),
                    "name": rider_name.strip(),
                    "profile_path": f"/people/{pid}/{date.today().year}",
                    "found_in_event": event["name"],
                }

    return None


# ── Rider profile ─────────────────────────────────────────────────────────────

def get_rider_profile(people_id: int, year: int = None) -> dict:
    """
    Fetch a rider's OBRA profile page and extract key fields.
    Returns a dict with name, categories, team, recent_results.
    """
    if year is None:
        year = date.today().year

    resp = _get(f"/people/{people_id}/{year}")
    html = _text(resp)
    if not html:
        return {"people_id": people_id, "error": "Profile not found"}

    profile: dict = {"people_id": people_id, "year": year}

    # Name — try <h1>, then <title>, then <h2>
    for pattern in (r'<h1[^>]*>\s*([^<]{2,60})\s*</h1>',
                    r'<title>\s*([^<|–-]{2,60}?)(?:\s*[|–-]|\s*</title>)',
                    r'<h2[^>]*>\s*([^<]{2,60})\s*</h2>'):
        m = re.search(pattern, html)
        if m:
            candidate = m.group(1).strip()
            # Reject JS-looking strings (camelCase, function keywords, digits-only)
            if not re.search(r'(function|var |const |let |document\.|window\.)', candidate):
                profile["name"] = candidate
                break

    # Road category — handles "Road (3)", "Road: 3", "Category 3", cell content
    for cat_pat in (r'Road\s*[\(:]?\s*(\d)\b',
                    r'cat(?:egory)?\s*(\d)\b',
                    r'<td[^>]*>\s*(\d)\s*</td>.*?road',
                    r'road.*?<td[^>]*>\s*(\d)\s*</td>'):
        m = re.search(cat_pat, html, re.IGNORECASE | re.DOTALL)
        if m and 1 <= int(m.group(1)) <= 5:
            profile["road_category"] = int(m.group(1))
            break
    if "road_category" not in profile:
        profile["road_category"] = None

    # Team — scan all /teams/ links and take the last one (appears at bottom of profile)
    team_matches = re.findall(r'href="/teams/\d+/\d+"[^>]*>([^<]+)</a>', html)
    profile["team"] = team_matches[-1].strip() if team_matches else None

    # License number
    m = re.search(r'License[:\s#]*(\d{4,})', html, re.IGNORECASE)
    profile["license"] = m.group(1) if m else None

    # Results — rows in results tables
    event_result_pattern = r'<tr[^>]*>(.*?)</tr>'
    results = []
    for row in re.findall(event_result_pattern, html, re.DOTALL):
        if '/events/' not in row:
            continue
        text = re.sub(r'<[^>]+>', ' ', row)
        text = re.sub(r'\s+', ' ', text).strip()
        if text and len(text) > 5:
            results.append(text)
    profile["recent_results"] = results[:15]
    profile["profile_url"] = f"{OBRA_BASE}/people/{people_id}/{year}"

    # Previous year
    prev_resp = _get(f"/people/{people_id}/{year - 1}")
    prev_html = _text(prev_resp)
    prev_results = []
    if prev_html:
        for row in re.findall(event_result_pattern, prev_html, re.DOTALL):
            if '/events/' not in row:
                continue
            text = re.sub(r'<[^>]+>', ' ', row)
            text = re.sub(r'\s+', ' ', text).strip()
            if text and len(text) > 5:
                prev_results.append(text)
        profile["prev_year_results"] = prev_results[:10]

    return profile


# ── Discover categories present in an event ───────────────────────────────────

def get_event_categories(event_id: int) -> list[dict]:
    """
    Scrape an OBRA event results page and return the categories present,
    with rider counts.  Fast — does NOT fetch individual rider profiles.

    Returns list of {label, category_int, count} sorted by category_int.
    Returns [] if the event has no results yet or can't be reached.
    """
    resp = _get(f"/events/{event_id}/results")
    html = _text(resp)
    if not html:
        return []

    # ── Strategy: find all headings in document order, then count person
    # links that fall between consecutive headings. Works regardless of
    # whether OBRA uses h3, h4, b, strong, td.event_bar, etc.

    # 1. Collect (position, raw_text) for every heading-like element
    heading_patterns = [
        re.compile(r'<h[1-6][^>]*>(.*?)</h[1-6]>', re.IGNORECASE | re.DOTALL),
        re.compile(r'<(?:b|strong)[^>]*>(.*?)</(?:b|strong)>', re.IGNORECASE | re.DOTALL),
        re.compile(r'<td[^>]+class="[^"]*(?:event_bar|category|header)[^"]*"[^>]*>(.*?)</td>',
                   re.IGNORECASE | re.DOTALL),
    ]

    headings: list[tuple[int, str]] = []
    for pat in heading_patterns:
        for m in pat.finditer(html):
            raw = re.sub(r'<[^>]+>', ' ', m.group(1))
            raw = re.sub(r'\s+', ' ', raw).strip()
            if not raw or len(raw) > 120:
                continue
            # Must look like a category (has digit, or key words)
            if re.search(r'\d|cat|junior|open|master|women|men\b', raw, re.IGNORECASE):
                headings.append((m.start(), raw))

    # Deduplicate overlapping matches (keep first occurrence per position)
    seen_pos: set[int] = set()
    unique_headings: list[tuple[int, str]] = []
    for pos, label in sorted(headings):
        if not any(abs(pos - s) < 50 for s in seen_pos):
            unique_headings.append((pos, label))
            seen_pos.add(pos)

    # 2. Collect positions of all person links
    person_positions = [m.start() for m in
                        re.finditer(r'href="/people/\d+/\d+"', html)]

    if not person_positions:
        return []

    # 3. If no category headings found at all, return one bucket "All riders"
    if not unique_headings:
        return [{
            "label": "All riders",
            "category_int": None,
            "count": len(set(person_positions)),
        }]

    # 4. Bucket person links between consecutive headings
    categories: list[dict] = []
    for i, (pos, label) in enumerate(unique_headings):
        next_pos = unique_headings[i + 1][0] if i + 1 < len(unique_headings) else len(html)
        count = sum(1 for p in person_positions if pos <= p < next_pos)
        if count == 0:
            continue
        cm = re.search(r'\b([1-5])\b', label)
        categories.append({
            "label": label,
            "category_int": int(cm.group(1)) if cm else None,
            "count": count,
        })

    # Sort: Cat 1→5 first, then non-numeric (open/junior/masters)
    categories.sort(key=lambda c: (c["category_int"] is None, c["category_int"] or 99))
    return categories


# ── Pull riders for a specific event by category ─────────────────────────────

def get_event_riders_by_category(event_id: int, target_category: int | None = None,
                                  target_label: str | None = None) -> list[dict]:
    """
    Given an OBRA event ID, return riders for a specific category.
    Uses the same position-based approach as get_event_categories so the
    heading detection is consistent.

    Returns list of {name, people_id, category, category_label, profile_path}
    """
    resp = _get(f"/events/{event_id}/results")
    html = _text(resp)
    if not html:
        return []

    # ── Re-use the same heading detection as get_event_categories ─────────────
    heading_patterns = [
        re.compile(r'<h[1-6][^>]*>(.*?)</h[1-6]>', re.IGNORECASE | re.DOTALL),
        re.compile(r'<(?:b|strong)[^>]*>(.*?)</(?:b|strong)>', re.IGNORECASE | re.DOTALL),
        re.compile(r'<td[^>]+class="[^"]*(?:event_bar|category|header)[^"]*"[^>]*>(.*?)</td>',
                   re.IGNORECASE | re.DOTALL),
    ]

    headings: list[tuple[int, str]] = []
    for pat in heading_patterns:
        for m in pat.finditer(html):
            raw = re.sub(r'<[^>]+>', ' ', m.group(1))
            raw = re.sub(r'\s+', ' ', raw).strip()
            if not raw or len(raw) > 120:
                continue
            if re.search(r'\d|cat|junior|open|master|women|men\b', raw, re.IGNORECASE):
                headings.append((m.start(), raw))

    # Deduplicate overlapping matches
    seen_pos: set[int] = set()
    unique_headings: list[tuple[int, str]] = []
    for pos, label in sorted(headings):
        if not any(abs(pos - s) < 50 for s in seen_pos):
            unique_headings.append((pos, label))
            seen_pos.add(pos)

    # ── Find the slice of HTML for the target category ────────────────────────
    if not unique_headings:
        # No headings — treat entire page as one category
        slice_start, slice_end = 0, len(html)
        section_label, section_cat = None, None
    else:
        slice_start, slice_end = 0, len(html)
        section_label, section_cat = None, None

        for i, (pos, label) in enumerate(unique_headings):
            cm = re.search(r'\b([1-5])\b', label)
            cat_int = int(cm.group(1)) if cm else None

            # Match by label first (exact), then by numeric category
            label_match = (target_label and label == target_label)
            cat_match = (target_label is None and target_category is not None
                         and cat_int == target_category)

            if label_match or cat_match or (target_label is None and target_category is None):
                slice_start = pos
                slice_end = unique_headings[i + 1][0] if i + 1 < len(unique_headings) else len(html)
                section_label = label
                section_cat = cat_int
                break

    html_slice = html[slice_start:slice_end]

    # ── Extract person links from that slice ──────────────────────────────────
    person_pat = re.compile(
        r'href="(/people/(\d+)/\d+)"[^>]*>\s*([^<]{2,80})\s*</a>',
        re.IGNORECASE,
    )

    riders: list[dict] = []
    seen_pids: set[int] = set()

    for m in person_pat.finditer(html_slice):
        path, pid_str, rname = m.group(1), m.group(2), m.group(3).strip()
        pid = int(pid_str)
        if not rname or rname.isdigit() or pid in seen_pids:
            continue
        seen_pids.add(pid)
        riders.append({
            "name": rname,
            "people_id": pid,
            "category": section_cat,
            "category_label": section_label,
            "profile_path": path,
        })

    return riders


def get_riders_for_event(
    event_id: int,
    target_category: int | None = None,
    progress_callback=None,
    target_label: str | None = None,
) -> list[dict]:
    """
    Fetch riders for an event and enrich each with their full OBRA profile.
    target_label takes priority over target_category when provided.
    """
    riders = get_event_riders_by_category(event_id, target_category, target_label)
    if not riders:
        return []

    enriched = []
    for i, r in enumerate(riders):
        if progress_callback:
            progress_callback(i, len(riders), r["name"])
        profile = get_rider_profile(r["people_id"])
        # Always carry the name from the event page as a fallback
        profile.setdefault("name", r["name"])
        profile["search_name"] = r["name"]
        # Use category from event page if profile parse failed
        if not profile.get("road_category") and r.get("category"):
            profile["road_category"] = r["category"]
        enriched.append(profile)

    return enriched


# ── Research a list of competitors ───────────────────────────────────────────

def research_competitors(names: list[str], progress_callback=None) -> list[dict]:
    """
    Given a list of competitor names, look up each on OBRA and return profiles.
    progress_callback(i, total, name) called for each rider to allow UI updates.
    """
    event_ids = get_recent_event_ids(limit=20)
    if not event_ids:
        return [{"name": n, "error": "Could not load OBRA events"} for n in names]

    results = []
    for i, name in enumerate(names):
        if progress_callback:
            progress_callback(i, len(names), name)

        name = name.strip()
        if not name:
            continue

        rider = find_rider_in_results(name, event_ids)
        if rider:
            profile = get_rider_profile(rider["people_id"])
            profile["search_name"] = name
            profile["found_in_event"] = rider["found_in_event"]
            results.append(profile)
        else:
            results.append({
                "search_name": name,
                "name": name,
                "error": "Not found in recent OBRA results",
                "people_id": None,
            })

    return results
