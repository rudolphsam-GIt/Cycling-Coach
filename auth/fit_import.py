from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from db.queries import get_setting, upsert_activity
from metrics.zones import estimate_zone_seconds

CYCLING_SPORT = {
    "cycling", "road_biking", "mountain_biking", "gravel_cycling",
    "virtual_ride", "indoor_cycling", "cycling_training",
    "generic",  # some Garmin devices record as generic
}


def _field(record, name, default=None):
    try:
        v = record.get_value(name)
        return v if v is not None else default
    except Exception:
        return default


def import_fit_files(uploaded_files) -> tuple[int, str]:
    try:
        from fitparse import FitFile
    except ImportError:
        return 0, "fitparse not installed. Run: venv/bin/pip install fitparse"

    ftp = float(get_setting("ftp_watts", 0) or 0)
    lthr = float(get_setting("lthr", 0) or 0)

    count = 0
    skipped = 0

    for uf in uploaded_files:
        try:
            raw = uf.read()
            ff = FitFile(raw)

            sport_type = "cycling"
            start_time = None
            total_elapsed = None
            total_timer = None
            distance_m = None
            elevation_m = None
            avg_power = None
            norm_power = None
            avg_hr = None
            max_hr = None
            name = uf.name.replace(".fit", "").replace("_", " ")

            for msg in ff.get_messages():
                mname = msg.name

                if mname == "sport":
                    s = _field(msg, "sport") or ""
                    sub = _field(msg, "sub_sport") or ""
                    combined = f"{s}_{sub}".lower().strip("_")
                    if "cycling" in combined or "biking" in combined or "virtual" in combined:
                        sport_type = combined or "cycling"
                    elif s.lower() not in ("", "generic"):
                        skipped += 1
                        break

                elif mname == "session":
                    ts = _field(msg, "start_time")
                    if isinstance(ts, datetime):
                        start_time = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
                    total_elapsed = _field(msg, "total_elapsed_time")
                    total_timer = _field(msg, "total_timer_time")
                    distance_m = _field(msg, "total_distance")
                    elevation_m = _field(msg, "total_ascent")
                    avg_power = _field(msg, "avg_power")
                    norm_power = _field(msg, "normalized_power")
                    avg_hr = _field(msg, "avg_heart_rate")
                    max_hr = _field(msg, "max_heart_rate")

                    display_name = _field(msg, "sport_profile_name") or name
                    if display_name:
                        name = display_name

            if not start_time:
                skipped += 1
                continue

            date_str = start_time.strftime("%Y-%m-%d")
            elapsed_s = float(total_elapsed or total_timer or 0)
            moving_s = float(total_timer or elapsed_s)

            # TSS
            if_val = (norm_power / ftp) if (norm_power and ftp) else None
            tss = ((elapsed_s / 3600) * (if_val ** 2) * 100) if if_val else None
            if tss is None and avg_hr and lthr:
                tss = (elapsed_s / 3600) * ((avg_hr / lthr) ** 2) * 100

            zones = estimate_zone_seconds(
                elapsed_s, avg_hr, max_hr, avg_power, norm_power, ftp, lthr
            )

            external_id = f"fit_{start_time.strftime('%Y%m%dT%H%M%S')}"

            upsert_activity({
                "source": "fit_import",
                "external_id": external_id,
                "date": date_str,
                "name": name,
                "sport_type": sport_type,
                "duration_seconds": int(moving_s),
                "elapsed_seconds": int(elapsed_s),
                "distance_meters": distance_m,
                "elevation_gain_meters": elevation_m,
                "avg_power_watts": avg_power,
                "normalized_power": norm_power,
                "avg_hr": avg_hr,
                "max_hr": max_hr,
                "tss": round(tss, 1) if tss else None,
                "if_value": round(if_val, 3) if if_val else None,
                "zone_time_json": json.dumps(zones) if zones else None,
                "raw_json": json.dumps({"source_file": uf.name}),
            })
            count += 1

        except Exception as e:
            skipped += 1
            continue

    if count == 0:
        return 0, f"No cycling activities found in the uploaded files ({skipped} skipped)."
    return count, f"Imported {count} ride{'s' if count != 1 else ''}" + (
        f" ({skipped} skipped — non-cycling or unreadable)" if skipped else "."
    )


# Garmin Connect CSV column name variants
_COL = {
    "activity_type": ["Activity Type", "activity_type"],
    "date":          ["Date", "date", "Start Time"],
    "title":         ["Title", "Activity Name", "title"],
    "distance":      ["Distance", "distance"],
    "time":          ["Time", "Duration", "Elapsed Time", "time"],
    "avg_hr":        ["Avg HR", "Average HR", "avg_hr"],
    "max_hr":        ["Max HR", "max_hr"],
    "avg_power":     ["Avg Power", "avg_power", "Average Power"],
    "norm_power":    ["Normalized Power (NP)", "Normalized Power", "norm_power"],
    "tss":           ["Training Stress Score®", "Training Stress Score", "TSS", "tss"],
    "elevation":     ["Total Ascent", "Elev Gain", "total_ascent"],
}

_CYCLING_KEYWORDS = {
    "cycling", "road", "gravel", "mountain", "mtb", "virtual", "indoor",
    "biking", "bike", "criterium", "crit", "cyclocross",
}


def _csv_val(row: dict, key: str, default=None):
    for col in _COL.get(key, []):
        v = row.get(col)
        if v is not None and str(v).strip() not in ("", "--"):
            return str(v).strip()
    return default


def _parse_duration(s: str) -> float | None:
    """Parse 'H:MM:SS' or 'MM:SS' or seconds string → float seconds."""
    if not s:
        return None
    s = s.strip()
    parts = s.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(s)
    except ValueError:
        return None


def _parse_float(s) -> float | None:
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def import_csv_files(uploaded_files) -> tuple[int, str]:
    ftp = float(get_setting("ftp_watts", 0) or 0)
    lthr = float(get_setting("lthr", 0) or 0)

    count = 0
    skipped = 0

    for uf in uploaded_files:
        try:
            text = uf.read().decode("utf-8-sig")  # strip BOM if present
            reader = csv.DictReader(io.StringIO(text))

            for row in reader:
                activity_type = (_csv_val(row, "activity_type") or "").lower()
                if not any(kw in activity_type for kw in _CYCLING_KEYWORDS):
                    skipped += 1
                    continue

                date_raw = _csv_val(row, "date")
                if not date_raw:
                    skipped += 1
                    continue

                # Parse date — Garmin uses "YYYY-MM-DD HH:MM:SS" or "YYYY-MM-DD"
                date_str = date_raw[:10]
                try:
                    datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    skipped += 1
                    continue

                elapsed_s = _parse_duration(_csv_val(row, "time")) or 0
                dist_raw = _parse_float(_csv_val(row, "distance"))
                # Garmin CSV distance is in km — convert to meters
                distance_m = dist_raw * 1000 if dist_raw else None
                elevation_m = _parse_float(_csv_val(row, "elevation"))
                avg_hr = _parse_float(_csv_val(row, "avg_hr"))
                max_hr = _parse_float(_csv_val(row, "max_hr"))
                avg_power = _parse_float(_csv_val(row, "avg_power"))
                norm_power = _parse_float(_csv_val(row, "norm_power"))
                tss_csv = _parse_float(_csv_val(row, "tss"))
                title = _csv_val(row, "title") or activity_type.title()

                # Compute TSS if not in CSV
                if_val = (norm_power / ftp) if (norm_power and ftp) else None
                tss = tss_csv
                if not tss and if_val:
                    tss = (elapsed_s / 3600) * (if_val ** 2) * 100
                if not tss and avg_hr and lthr:
                    tss = (elapsed_s / 3600) * ((avg_hr / lthr) ** 2) * 100

                zones = estimate_zone_seconds(
                    elapsed_s, avg_hr, max_hr, avg_power, norm_power, ftp, lthr
                )

                external_id = f"csv_{date_str}_{title[:20].replace(' ', '_')}"

                upsert_activity({
                    "source": "csv_import",
                    "external_id": external_id,
                    "date": date_str,
                    "name": title,
                    "sport_type": activity_type,
                    "duration_seconds": int(elapsed_s),
                    "elapsed_seconds": int(elapsed_s),
                    "distance_meters": distance_m,
                    "elevation_gain_meters": elevation_m,
                    "avg_power_watts": avg_power,
                    "normalized_power": norm_power,
                    "avg_hr": int(avg_hr) if avg_hr else None,
                    "max_hr": int(max_hr) if max_hr else None,
                    "tss": round(tss, 1) if tss else None,
                    "if_value": round(if_val, 3) if if_val else None,
                    "zone_time_json": json.dumps(zones) if zones else None,
                    "raw_json": json.dumps({"source_file": uf.name}),
                })
                count += 1

        except Exception:
            skipped += 1
            continue

    if count == 0:
        return 0, f"No cycling rows found in CSV ({skipped} skipped)."
    return count, f"Imported {count} ride{'s' if count != 1 else ''} from CSV" + (
        f" ({skipped} skipped)" if skipped else "."
    )
