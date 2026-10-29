from __future__ import annotations

import csv
import gzip
import io
import json
import os
import sports
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from db.queries import (get_setting, upsert_activity, save_peaks, save_hr_peaks, save_streams,
                        ftp_history_rows, ftp_on, hr_profile, rescore_from_streams)
from metrics.tss import ride_tss, time_rule, tss_duration
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


def _save_file_peaks(activity_id, raw: bytes) -> None:
    """Best power and heart rate by duration from the file's second by second data."""
    from metrics.analysis import PEAK_DURATIONS
    from metrics.peaks import HR_DURATIONS, fit_streams, mean_max
    if not activity_id:
        return
    try:
        hr, power = fit_streams(raw)
    except Exception:
        return
    save_peaks(activity_id, mean_max(power, PEAK_DURATIONS))
    try:
        from metrics.streams import from_fit
        save_streams(activity_id, from_fit(raw), "fit_import")
        rescore_from_streams(activity_id)
    except Exception:
        pass
    save_hr_peaks(activity_id, mean_max(hr, HR_DURATIONS, zero_is_missing=True))


# What the ride uploaders take. A .fit.gz ends in .gz, which is how the uploader sees it.
RIDE_FILE_TYPES = ["fit", "gz", "zip"]
RIDE_FILE_HELP = ("Takes .fit files, .fit.gz files, or a .zip of either, such as a whole Strava or "
                  "Garmin Connect export.")
# A whole export can hold many years. Rides older than a year add little (HISTORY_ASK), so files
# that come out of a zip and started before this are left out. Files picked one by one all import.
ARCHIVE_DAYS = 365
_OTHER_FORMATS = (".gpx", ".tcx", ".gpx.gz", ".tcx.gz")


@dataclass
class _RideFile:
    """A ride unpacked from a .gz or .zip, shaped like an uploaded file for import_fit_files."""
    name: str
    data: bytes

    def read(self) -> bytes:
        return self.data


def expand_ride_files(uploaded_files, today: date | None = None) -> tuple[list, dict]:
    """The .fit files in an upload. Loose .fit files pass through, .fit.gz files are unpacked, and
    a .zip is searched for both, including zips inside it as Garmin's export has. Returns the files
    and counts of what was left out: older (from a zip, over ARCHIVE_DAYS old), other_format
    (GPX or TCX, which this importer doesn't read) and unreadable."""
    cutoff = (today or date.today()) - timedelta(days=ARCHIVE_DAYS)
    files, counts = [], {"older": 0, "other_format": 0, "unreadable": 0}
    for uf in uploaded_files:
        _expand(uf.name, uf.read(), False, cutoff, files, counts)
    return files, counts


def _expand(name: str, data: bytes, from_zip: bool, cutoff: date, files: list, counts: dict) -> None:
    low = name.lower()
    if low.endswith(".zip"):
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            counts["unreadable"] += 1
            return
        for info in z.infolist():
            inner = info.filename.lower()
            if info.is_dir() or "__macosx" in inner:
                continue
            if inner.endswith((".zip", ".fit", ".fit.gz")):
                # Only rides are read out of the zip, so photos and the rest of an export never load.
                _expand(info.filename, z.read(info), True, cutoff, files, counts)
            elif inner.endswith(_OTHER_FORMATS):
                counts["other_format"] += 1
        return
    if low.endswith(_OTHER_FORMATS):
        counts["other_format"] += 1
        return
    if low.endswith(".gz"):
        try:
            data = gzip.decompress(data)
        except (OSError, EOFError):
            counts["unreadable"] += 1
            return
        name, low = name[:-3], low[:-3]
    if not low.endswith(".fit"):
        counts["unreadable"] += 1
        return
    started = _fit_created(data) if from_zip else None
    if started and started < cutoff:
        counts["older"] += 1
        return
    files.append(_RideFile(os.path.basename(name), data))


def _fit_created(raw: bytes) -> date | None:
    """When a FIT file was recorded, from its first message, without parsing the rest."""
    try:
        from fitparse import FitFile
        for msg in FitFile(raw).get_messages("file_id"):
            ts = _field(msg, "time_created")
            return ts.date() if isinstance(ts, datetime) else None
    except Exception:
        return None
    return None


def import_ride_files(uploaded_files, today: date | None = None) -> tuple[int, str]:
    """import_fit_files for anything the ride uploaders take, with a word on what was left out."""
    files, counts = expand_ride_files(uploaded_files, today)
    imported, message = import_fit_files(files) if files else (0, "No .fit files were found in the upload.")
    def n(k, word):
        return f"{counts[k]} {word}{'s' if counts[k] != 1 else ''}"
    left_out = [text for k, text in (
        ("older", n("older", "ride") + " from more than a year ago"),
        ("other_format", n("other_format", "GPX or TCX file") + " the app can't read"),
        ("unreadable", n("unreadable", "file") + " that couldn't be opened"),
    ) if counts[k]]
    if left_out:
        listed = ", ".join(left_out[:-1]) + " and " + left_out[-1] if len(left_out) > 1 else left_out[0]
        message = message.rstrip(".") + ". Left out " + listed + "."
    return imported, message


def import_fit_files(uploaded_files) -> tuple[int, str]:
    try:
        from fitparse import FitFile
    except ImportError:
        return 0, "fitparse not installed. Run: venv/bin/pip install fitparse"

    history = ftp_history_rows()
    profile = hr_profile()
    lthr = float(get_setting("lthr", 0) or 0)

    ski_lthr = sports.ski_lthr()
    count = rides = 0
    skipped = 0

    for uf in uploaded_files:
        try:
            raw = uf.read()
            ff = FitFile(raw)

            sport_type = "cycling"
            start_time = None
            total_elapsed = None
            total_timer = None
            total_moving = None
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
                        # Skiing, runs and other sports count toward fitness too, scored from heart
                        # rate (skiing on the ski threshold when one is set), as Garmin sync does.
                        sport_type = combined

                elif mname == "session":
                    ts = _field(msg, "start_time")
                    if isinstance(ts, datetime):
                        start_time = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
                    total_elapsed = _field(msg, "total_elapsed_time")
                    total_timer = _field(msg, "total_timer_time")
                    total_moving = _field(msg, "total_moving_time")
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
            moving_s = float(total_moving or total_timer or elapsed_s)

            is_bike = "cycling" in sport_type or "biking" in sport_type or "virtual" in sport_type
            if not is_bike and not avg_hr:
                skipped += 1            # another sport with no heart rate can't be scored
                continue

            # TSS
            tss_s = tss_duration(moving_s, elapsed_s, total_timer, time_rule(profile))
            ride_ftp = ftp_on(date_str, history)
            act_lthr = sports.threshold_for(sport_type, lthr, ski_lthr)
            tss, if_val, tss_source = ride_tss(tss_s, norm_power if is_bike else None, avg_hr, max_hr,
                                               ride_ftp if is_bike else None, act_lthr, profile=profile)

            zones = estimate_zone_seconds(
                tss_s, avg_hr, max_hr, avg_power, norm_power, ride_ftp, act_lthr
            )

            external_id = f"fit_{start_time.strftime('%Y%m%dT%H%M%S')}"

            activity_id = upsert_activity({
                "source": "fit_import",
                "external_id": external_id,
                "date": date_str,
                "name": name,
                "sport_type": sport_type,
                "duration_seconds": int(moving_s),
                "timer_seconds": int(total_timer) if total_timer else None,
                "elapsed_seconds": int(elapsed_s),
                "distance_meters": distance_m,
                "elevation_gain_meters": elevation_m,
                "avg_power_watts": avg_power,
                "normalized_power": norm_power,
                "avg_hr": avg_hr,
                "max_hr": max_hr,
                "tss": round(tss, 1) if tss else None,
                "tss_source": tss_source if tss else None,
                "if_value": round(if_val, 3) if if_val else None,
                "zone_time_json": json.dumps(zones) if zones else None,
                "raw_json": json.dumps({"source_file": uf.name}),
            })
            _save_file_peaks(activity_id, raw)
            count += 1
            rides += is_bike

        except Exception as e:
            skipped += 1
            continue

    if count == 0:
        return 0, f"No activities could be read from the uploaded files ({skipped} skipped)."
    others = count - rides
    what = f"{rides} ride{'s' if rides != 1 else ''}" + (
        f" and {others} other activit{'ies' if others != 1 else 'y'} (skiing, runs and the like)" if others else "")
    return count, f"Imported {what}" + (
        f" ({skipped} skipped, unreadable or with no heart rate)" if skipped else "."
    )


# Garmin Connect CSV column name variants
_COL = {
    "activity_type": ["Activity Type", "activity_type"],
    "date":          ["Date", "date", "Start Time"],
    "title":         ["Title", "Activity Name", "title"],
    "distance":      ["Distance", "distance"],
    "time":          ["Time", "Duration", "Elapsed Time", "time"],
    "moving_time":   ["Moving Time", "moving_time"],
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


def import_csv_files(uploaded_files, imperial: bool = False) -> tuple[int, str]:
    """Import a Garmin Connect CSV export. Set imperial=True if it's in miles and feet."""
    history = ftp_history_rows()
    profile = hr_profile()
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
                moving_s = _parse_duration(_csv_val(row, "moving_time")) or elapsed_s
                dist_raw = _parse_float(_csv_val(row, "distance"))
                # Garmin CSV distance is in miles or km, depending on the account's units
                distance_m = dist_raw * (1609.344 if imperial else 1000) if dist_raw else None
                elevation_raw = _parse_float(_csv_val(row, "elevation"))
                elevation_m = (elevation_raw * 0.3048 if imperial else elevation_raw) if elevation_raw else elevation_raw
                avg_hr = _parse_float(_csv_val(row, "avg_hr"))
                max_hr = _parse_float(_csv_val(row, "max_hr"))
                avg_power = _parse_float(_csv_val(row, "avg_power"))
                norm_power = _parse_float(_csv_val(row, "norm_power"))
                tss_csv = _parse_float(_csv_val(row, "tss"))
                title = _csv_val(row, "title") or activity_type.title()

                # Compute TSS if not in CSV
                ride_ftp = ftp_on(date_str, history)
                tss, if_val, tss_source = ride_tss(tss_duration(moving_s, elapsed_s, elapsed_s, time_rule(profile)),
                                                   norm_power, avg_hr, max_hr, ride_ftp, lthr, profile=profile)
                if tss_csv:
                    tss, tss_source = tss_csv, None

                zones = estimate_zone_seconds(
                    elapsed_s, avg_hr, max_hr, avg_power, norm_power, ride_ftp, lthr
                )

                external_id = f"csv_{date_str}_{title[:20].replace(' ', '_')}"

                upsert_activity({
                    "source": "csv_import",
                    "external_id": external_id,
                    "date": date_str,
                    "name": title,
                    "sport_type": activity_type,
                    "duration_seconds": int(moving_s),
                    "timer_seconds": int(elapsed_s) or None,    # Garmin's "Time" is timer time
                    "elapsed_seconds": int(elapsed_s),
                    "distance_meters": distance_m,
                    "elevation_gain_meters": elevation_m,
                    "avg_power_watts": avg_power,
                    "normalized_power": norm_power,
                    "avg_hr": int(avg_hr) if avg_hr else None,
                    "max_hr": int(max_hr) if max_hr else None,
                    "tss": round(tss, 1) if tss else None,
                    "tss_source": tss_source if tss else None,
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
