from __future__ import annotations

"""
Search public cycling platforms for a competitor's power/FTP data.

Sources tried (in order):
1. ZwiftPower — public athlete search, shows CP/FTP for Zwift racers
2. DuckDuckGo web search — finds public Strava/Garmin/TrainingPeaks profile URLs

This is best-effort: not every rider will be found. When found, data is from
their own published numbers, so confidence is high.
"""

import re
import time

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

ZWIFT_SEARCH = "https://zwiftpower.com/api3.php"
DDG_SEARCH = "https://duckduckgo.com/html/"


def _get(url: str, params: dict | None = None, timeout: int = 10) -> str:
    try:
        r = requests.get(url, headers=HEADERS, params=params or {}, timeout=timeout)
        r.raise_for_status()
        time.sleep(0.5)
        return r.text
    except Exception:
        return ""


# ── ZwiftPower ────────────────────────────────────────────────────────────────

def _search_zwiftpower(name: str) -> dict | None:
    """
    Search ZwiftPower for a rider and return their CP (critical power / FTP).
    ZwiftPower shows wkg and FTP on public athlete pages.
    """
    html = _get(ZWIFT_SEARCH, {"do": "search_riders", "search": name})
    if not html:
        return None

    # Response is JSON array of [{zwid, name, ftp, wkg, ...}]
    import json
    try:
        data = json.loads(html)
    except Exception:
        return None

    if not isinstance(data, list) or not data:
        return None

    # Find best name match
    name_lower = name.lower()
    name_parts = set(name_lower.split())

    for entry in data:
        zname = str(entry.get("name", "")).lower()
        zparts = set(zname.split())
        if name_parts.issubset(zparts) or zparts.issubset(name_parts):
            ftp = entry.get("ftp") or entry.get("cp")
            wkg = entry.get("wkg")
            if ftp or wkg:
                return {
                    "source": "ZwiftPower",
                    "ftp_est": int(ftp) if ftp else None,
                    "wkg_est": float(wkg) if wkg else None,
                    "profile_url": f"https://zwiftpower.com/profile.php?z={entry.get('zwid', '')}",
                    "confidence": "High",
                    "note": f"ZwiftPower public profile — {entry.get('name', name)}",
                }

    return None


# ── DuckDuckGo web search ─────────────────────────────────────────────────────

def _ddg_search(query: str) -> list[dict]:
    """Return top web results [{title, url, snippet}] from DuckDuckGo."""
    html = _get(DDG_SEARCH, {"q": query, "kl": "us-en"})
    if not html:
        return []

    results = []
    # DDG HTML results: <a class="result__a" href="URL">Title</a>
    for m in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([^<]+)</a>',
        html, re.IGNORECASE
    ):
        url, title = m.group(1), m.group(2).strip()
        if url.startswith("http"):
            results.append({"url": url, "title": title})
        if len(results) >= 5:
            break
    return results


def _find_public_profiles(name: str) -> dict:
    """
    Search for a rider's public cycling profiles via DuckDuckGo.
    Returns links to found profiles + any extractable FTP hints.
    """
    found: dict = {"profiles": [], "ftp_hints": []}

    # Search for Strava profile
    for query in [
        f'site:strava.com/athletes "{name}"',
        f'"{name}" cycling strava OR zwift OR garmin',
    ]:
        results = _ddg_search(query)
        for r in results:
            url = r["url"]
            if "strava.com/athletes/" in url:
                found["profiles"].append({"platform": "Strava", "url": url,
                                          "title": r["title"]})
            elif "zwiftpower.com/profile" in url:
                found["profiles"].append({"platform": "ZwiftPower", "url": url,
                                          "title": r["title"]})
            elif "intervals.icu/athletes/" in url:
                found["profiles"].append({"platform": "Intervals.icu", "url": url,
                                          "title": r["title"]})
            elif "connect.garmin.com" in url:
                found["profiles"].append({"platform": "Garmin Connect", "url": url,
                                          "title": r["title"]})

            # Look for FTP mentions in the snippet
            ftp_m = re.search(r'\bFTP[:\s]+(\d{2,3})\s*[Ww]\b', r.get("title", ""))
            if ftp_m:
                found["ftp_hints"].append(int(ftp_m.group(1)))

    # Deduplicate profiles
    seen_urls = set()
    unique = []
    for p in found["profiles"]:
        if p["url"] not in seen_urls:
            seen_urls.add(p["url"])
            unique.append(p)
    found["profiles"] = unique[:4]

    return found


# ── Public entry point ────────────────────────────────────────────────────────

def search_public_power(name: str) -> dict:
    """
    Try ZwiftPower first, then web search for public profiles.

    Returns:
      {
        zwiftpower: dict | None,   # ftp_est, wkg_est, profile_url, confidence, note
        profiles: list[dict],      # [{platform, url, title}]
        ftp_hints: list[int],      # any FTP numbers found in web snippets
      }
    """
    zp = _search_zwiftpower(name)
    profiles_data = _find_public_profiles(name)

    return {
        "zwiftpower": zp,
        "profiles": profiles_data.get("profiles", []),
        "ftp_hints": profiles_data.get("ftp_hints", []),
    }
