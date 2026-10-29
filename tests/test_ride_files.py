import gzip
import io
import os
import tempfile
import unittest
import zipfile
from datetime import date, datetime, timezone
from unittest import mock

from auth import fit_import
from db import schema
from db import queries as q

TODAY = date(2026, 10, 29)


def _fit(day: date, hour: int = 15) -> bytes:
    """A small cycling activity recorded on day, built the way a head unit writes one."""
    from fit_tool.fit_file_builder import FitFileBuilder
    from fit_tool.profile.messages.file_id_message import FileIdMessage
    from fit_tool.profile.messages.session_message import SessionMessage
    from fit_tool.profile.profile_type import FileType, Manufacturer, Sport
    ms = int(datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc).timestamp() * 1000)
    fid = FileIdMessage()
    fid.type, fid.manufacturer, fid.time_created = FileType.ACTIVITY, Manufacturer.DEVELOPMENT.value, ms
    s = SessionMessage()
    s.start_time, s.sport = ms, Sport.CYCLING
    s.total_elapsed_time = s.total_timer_time = 3600
    s.avg_heart_rate, s.max_heart_rate, s.avg_power = 140, 170, 180
    b = FitFileBuilder(auto_define=True)
    b.add(fid)
    b.add(s)
    return b.build().to_bytes()


def _zip(entries: dict) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return out.getvalue()


class _Upload:
    def __init__(self, name, data):
        self.name, self._data = name, data

    def read(self):
        return self._data


RECENT, OLD = date(2026, 10, 1), date(2025, 6, 1)


class ExpandTests(unittest.TestCase):
    def _expand(self, *uploads):
        files, counts = fit_import.expand_ride_files([_Upload(n, d) for n, d in uploads], today=TODAY)
        return [f.name for f in files], counts

    def test_loose_fit_files_all_come_in_however_old(self):
        names, counts = self._expand(("a.fit", _fit(RECENT)), ("b.fit", _fit(OLD)))
        self.assertEqual(names, ["a.fit", "b.fit"])
        self.assertEqual(counts["older"], 0)

    def test_fit_gz_is_unpacked(self):
        files, _ = fit_import.expand_ride_files([_Upload("123.fit.gz", gzip.compress(_fit(RECENT)))])
        self.assertEqual(files[0].name, "123.fit")
        self.assertEqual(files[0].read(), _fit(RECENT))

    def test_strava_style_export(self):
        export = _zip({
            "activities/1.fit.gz": gzip.compress(_fit(RECENT)),
            "activities/2.fit.gz": gzip.compress(_fit(OLD)),
            "activities/3.gpx": b"<gpx/>",
            "activities/4.tcx.gz": gzip.compress(b"<tcx/>"),
            "media/photo.jpg": b"\xff\xd8",
            "activities.csv": b"Activity ID,Filename\n",
            "__MACOSX/activities/._1.fit.gz": b"junk",
        })
        names, counts = self._expand(("export_123.zip", export))
        self.assertEqual(names, ["1.fit"])
        self.assertEqual(counts, {"older": 1, "other_format": 2, "unreadable": 0})

    def test_garmin_style_zip_inside_a_zip(self):
        inner = _zip({"me_111.fit": _fit(RECENT), "me_222.fit": _fit(RECENT, hour=18)})
        export = _zip({"DI_CONNECT/DI-Connect-Uploaded-Files/UploadedFiles_0-_Part1.zip": inner,
                       "DI_CONNECT/DI-Connect-User/user_profile.json": b"{}"})
        names, counts = self._expand(("garmin.zip", export))
        self.assertEqual(sorted(names), ["me_111.fit", "me_222.fit"])
        self.assertEqual(counts["older"], 0)

    def test_broken_files_are_counted_not_raised(self):
        names, counts = self._expand(("bad.zip", b"not a zip"), ("bad.fit.gz", b"not gzip"))
        self.assertEqual(names, [])
        self.assertEqual(counts["unreadable"], 2)


class ImportRideFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        q._settings_cache.clear()
        schema.run_migrations()

    def test_export_imports_recent_rides_and_says_what_was_left_out(self):
        export = _zip({"a/1.fit.gz": gzip.compress(_fit(RECENT)),
                       "a/2.fit.gz": gzip.compress(_fit(date(2026, 10, 8))),
                       "a/3.fit.gz": gzip.compress(_fit(OLD)),
                       "a/4.gpx": b"<gpx/>"})
        n, message = fit_import.import_ride_files([_Upload("export.zip", export)], today=TODAY)
        self.assertEqual(n, 2)
        self.assertIn("Imported 2 rides", message)
        self.assertIn("Left out 1 ride from more than a year ago and 1 GPX or TCX file the app can't read.",
                      message)

    def test_a_zip_with_no_rides_says_so(self):
        n, message = fit_import.import_ride_files([_Upload("x.zip", _zip({"a.gpx": b"<gpx/>"}))],
                                                  today=TODAY)
        self.assertEqual(n, 0)
        self.assertIn("No .fit files were found", message)


if __name__ == "__main__":
    unittest.main()
