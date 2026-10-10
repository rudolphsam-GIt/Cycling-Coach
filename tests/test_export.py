"""Exporting the plan: Zwift files, zips, saved steps, intervals.icu and the TrainingPeaks calendar.
Nothing here talks to a real service; HTTP goes to a fake session that records each call.
Run with venv/bin/python -m unittest tests.test_export -v"""
import io
import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, timedelta
from unittest import mock

import exporters
import garmin_workouts
from auth import intervals, trainingpeaks as tp
from db import schema, queries as q

TODAY = date.today()
D = lambda n: (TODAY + timedelta(days=n)).isoformat()

STEPS = [
    {"kind": "warmup", "minutes": 10, "low_pct": 50, "high_pct": 65},
    {"kind": "repeat", "repeat_count": 3, "repeat_steps": [
        {"kind": "interval", "minutes": 15, "low_pct": 88, "high_pct": 92},
        {"kind": "recovery", "minutes": 5, "low_pct": 45, "high_pct": 55}]},
    {"kind": "cooldown", "minutes": 10, "low_pct": 45, "high_pct": 60},
]
W = {"id": 7, "date": D(3), "name": "Sweet spot 3x15", "workout_type": "Threshold", "tss_planned": 85,
     "purpose": "Raises the power you can hold.", "feel": "7 out of 10.", "description": "3x15 at 90%"}


class Response:
    def __init__(self, status=200, data=None, text=""):
        self.status_code, self._data, self.text = status, data, text
        self.content = b"" if data is None else json.dumps(data).encode()

    def json(self):
        if self._data is None:
            raise ValueError("no body")
        return self._data


class FakeSession:
    """Records calls. `routes` maps (METHOD, url start) to a Response or a function of the call."""

    def __init__(self, routes=None):
        self.calls, self.routes, self.headers, self.auth = [], routes or {}, {}, None

    def _go(self, method, url, **kw):
        self.calls.append({"method": method, "url": url, **kw})
        for (m, prefix), resp in self.routes.items():
            if m == method and url.startswith(prefix):
                return resp(self.calls[-1]) if callable(resp) else resp
        return Response(200, {})

    def get(self, url, **kw): return self._go("GET", url, **kw)
    def post(self, url, **kw): return self._go("POST", url, **kw)
    def put(self, url, **kw): return self._go("PUT", url, **kw)
    def delete(self, url, **kw): return self._go("DELETE", url, **kw)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        schema.run_migrations()
        q.set_setting("ftp_watts", "300")

    def ride(self, day, name="Tempo", tss=70, **kw):
        wid = q.add_workout({"date": day, "name": name, "workout_type": "Tempo", "description": "2x20",
                             "structured_json": None, "tss_planned": tss, "notes": "", **kw})
        return q.get_workout(wid)


# ── Zwift files ───────────────────────────────────────────────────────────────

class ZwoTests(unittest.TestCase):
    def parse(self, text):
        return ET.fromstring(text)

    def test_the_shape_matches_zwifts_own_files(self):
        root = self.parse(exporters.to_zwo(W, STEPS))
        self.assertEqual(root.findtext("sportType"), "bike")
        self.assertEqual(root.findtext("name"), "Sweet spot 3x15")
        body = list(root.find("workout"))
        self.assertEqual([e.tag for e in body], ["Warmup", "IntervalsT", "Cooldown"])
        warm, ints, cool = body
        self.assertEqual((warm.get("Duration"), warm.get("PowerLow"), warm.get("PowerHigh")), ("600", "0.5", "0.65"))
        self.assertEqual((ints.get("Repeat"), ints.get("OnDuration"), ints.get("OffDuration")), ("3", "900", "300"))
        self.assertEqual((ints.get("OnPower"), ints.get("OffPower")), ("0.9", "0.5"))
        # Zwift's cool down runs from PowerLow to PowerHigh, so it starts high and ends low
        self.assertEqual((cool.get("PowerLow"), cool.get("PowerHigh")), ("0.6", "0.45"))

    def test_steady_steps_free_rides_and_odd_repeats(self):
        steps = [{"kind": "interval", "minutes": 60, "low_pct": 56, "high_pct": 75},
                 {"kind": "interval", "minutes": 5, "low_pct": None, "high_pct": None},
                 {"kind": "repeat", "repeat_count": 2, "repeat_steps": [
                     {"kind": "interval", "minutes": 1, "low_pct": 120, "high_pct": 130},
                     {"kind": "recovery", "minutes": 1, "low_pct": 50, "high_pct": 55},
                     {"kind": "interval", "minutes": 2, "low_pct": 100, "high_pct": 105}]}]
        body = list(self.parse(exporters.to_zwo({**W, "feel": None}, steps)).find("workout"))
        self.assertEqual([e.tag for e in body], ["SteadyState", "FreeRide"] + ["SteadyState"] * 6)
        self.assertEqual(body[0].get("Power"), "0.655")
        self.assertEqual(body[0].get("Duration"), "3600")

    def test_the_feel_cue_shows_once_on_the_first_hard_part(self):
        steps = [{"kind": "warmup", "minutes": 10, "low_pct": 50, "high_pct": 65},
                 {"kind": "interval", "minutes": 20, "low_pct": 76, "high_pct": 85},
                 {"kind": "interval", "minutes": 20, "low_pct": 76, "high_pct": 85}]
        body = list(self.parse(exporters.to_zwo(W, steps)).find("workout"))
        events = [e.find("textevent") for e in body]
        self.assertIsNone(events[0])
        self.assertEqual(events[1].get("message"), "7 out of 10.")
        self.assertIsNone(events[2])

    def test_awkward_text_is_escaped(self):
        w = {**W, "name": 'Over & unders <hard> "fun"', "purpose": "5 < 6 & 7 > 4", "feel": 'Say "ouch" & <go>'}
        root = self.parse(exporters.to_zwo(w, [{"kind": "interval", "minutes": 5, "low_pct": 90, "high_pct": 95}]))
        self.assertEqual(root.findtext("name"), 'Over & unders <hard> "fun"')
        self.assertIn("5 < 6 & 7 > 4", root.findtext("description"))
        self.assertEqual(root.find("workout")[0].find("textevent").get("message"), 'Say "ouch" & <go>')

    def test_names_and_titles_carry_the_date(self):
        self.assertEqual(exporters.file_base({"date": "2026-10-12", "name": "Tempo blocks!"}), "2026-10-12_Tempo_blocks")
        self.assertEqual(exporters.dated_title({"date": "2026-10-12", "name": "Tempo blocks"}), "2026-10-12 Tempo blocks")
        self.assertEqual(exporters.file_base({"date": "2026-10-12", "name": "   "}), "2026-10-12_workout")


class ZipTests(Base):
    def rows(self):
        a = {**W, "id": 1, "date": D(1), "name": "Tempo"}
        b = {**W, "id": 2, "date": D(1), "name": "Tempo"}           # same day and name, names must not clash
        c = {**W, "id": 3, "date": D(2), "name": "Long ride"}
        return [(a, STEPS), (b, STEPS), (c, STEPS)]

    def test_the_trainingpeaks_zip_has_dated_zwo_files_and_instructions(self):
        zf = zipfile.ZipFile(io.BytesIO(exporters.trainingpeaks_zip(self.rows(), "Off season")))
        names = sorted(zf.namelist())
        self.assertEqual(names, sorted([f"{D(1)}_Tempo.zwo", f"{D(1)}_Tempo_2.zwo", f"{D(2)}_Long_ride.zwo",
                                        "HOW_TO_IMPORT.txt"]))
        root = ET.fromstring(zf.read(f"{D(2)}_Long_ride.zwo"))
        self.assertEqual(root.findtext("name"), f"{D(2)} Long ride")          # the library lists by date
        self.assertIn("Off season", zf.read("HOW_TO_IMPORT.txt").decode())

    def test_the_full_zip_has_zwo_fit_csv_and_instructions(self):
        zf = zipfile.ZipFile(io.BytesIO(exporters.all_files_zip(self.rows())))
        names = zf.namelist()
        self.assertEqual(sum(n.startswith("zwo/") for n in names), 3)
        self.assertEqual(sum(n.startswith("fit/") for n in names), 3)
        self.assertIn("plan.csv", names)
        self.assertIn("HOW_TO_IMPORT.txt", names)
        for n in names:
            if n.endswith(".zwo"):
                ET.fromstring(zf.read(n))
        fit = zf.read(next(n for n in names if n.endswith(".fit")))
        self.assertEqual(fit[8:12], b".FIT")
        lines = zf.read("plan.csv").decode().splitlines()
        self.assertEqual(lines[0], "date,name,type,minutes,tss,purpose,feel")
        self.assertEqual(len(lines), 4)
        self.assertIn(",80,", lines[1])                                  # 10 + 3 x 20 + 10 minutes

    def test_the_instructions_avoid_em_dashes(self):
        self.assertNotIn("—", exporters.HOW_TO)
        for text in (exporters.guide_text("X", exporters.CONTENTS), " ".join(exporters.CONTENTS)):
            self.assertNotIn("—", text)
            self.assertNotIn("–", text)
            self.assertNotIn(" - ", text)

    def test_the_guide_claims_only_what_was_confirmed(self):
        text = exporters.guide_text("X", exporters.CONTENTS)
        self.assertIn("Import Workout", text)
        self.assertIn("NewFiles", text)
        self.assertIn("not confirmed it for Forerunner", text)
        self.assertNotIn("Upload", text)


OPEN_STEPS = [{"kind": "warmup", "minutes": 5, "low_pct": None, "high_pct": None},
              {"kind": "interval", "minutes": 20, "low_pct": None, "high_pct": None}]


class IcsTests(Base):
    def rows(self):
        return [({**W, "id": 1, "date": "2026-10-12", "name": "Tempo, long; hard\\ \u65e5\u672c" + "x" * 90}, STEPS),
                ({**W, "id": 2, "date": "2026-10-13", "name": "Open", "purpose": "Line one\nLine two"}, OPEN_STEPS)]

    def unfold(self, text):
        return text.replace("\r\n ", "")

    def test_it_is_a_valid_calendar_with_crlf_and_short_lines(self):
        ics = exporters.plan_ics(self.rows(), "Alex", 300)
        raw = ics.encode("utf-8")
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertTrue(ics.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"))
        self.assertTrue(ics.endswith("END:VCALENDAR\r\n"))
        for line in raw.split(b"\r\n"):
            self.assertLessEqual(len(line), 75)
            line.decode("utf-8")                       # no character was split in half
        flat = self.unfold(ics)
        for want in ("PRODID:", "CALSCALE:GREGORIAN", "X-WR-CALNAME:Alex training plan"):
            self.assertIn(want, flat)

    def test_one_event_per_workout_with_stable_ids_and_all_day_dates(self):
        a, b = exporters.plan_ics(self.rows(), "Alex", 300), exporters.plan_ics(self.rows(), "Alex", 300)
        flat = self.unfold(a)
        self.assertEqual(flat.count("BEGIN:VEVENT"), 2)
        self.assertIn("UID:cc-1-2026-10-12@cycling-coach", flat)
        self.assertIn("DTSTART;VALUE=DATE:20261012", flat)
        self.assertIn("DTEND;VALUE=DATE:20261013", flat)
        uids = lambda t: [l for l in self.unfold(t).split("\r\n") if l.startswith("UID:")]
        self.assertEqual(uids(a), uids(b))

    def test_text_is_escaped_and_the_description_has_watts(self):
        flat = self.unfold(exporters.plan_ics(self.rows(), "Alex", 300))
        self.assertIn("Tempo\\, long\\; hard\\\\", flat)
        self.assertIn("Line one\\nLine two", flat)
        self.assertIn("3 rounds of Ride 15 min at 264 to 276 W (88 to 92% FTP)", flat)
        self.assertIn("with no power target", flat)               # open power does not break it

    def test_no_athlete_name_still_works(self):
        self.assertIn("X-WR-CALNAME:Training plan", exporters.plan_ics(self.rows()))


class SharePackageTests(Base):
    def rows(self):
        return [({**W, "id": 1, "date": D(1)}, STEPS), ({**W, "id": 2, "date": D(2), "name": "Open"}, OPEN_STEPS)]

    def test_the_zip_has_one_named_folder_with_everything(self):
        zf = zipfile.ZipFile(io.BytesIO(exporters.share_package_zip(self.rows(), "Alex", 300)))
        names = zf.namelist()
        self.assertTrue(all(n.startswith("Alex training plan/") for n in names))
        inner = {n.split("/", 1)[1] for n in names}
        for want in ("Plan.pdf", "How to import.pdf", "HOW_TO_IMPORT.txt", "plan.ics", "plan.csv"):
            self.assertIn(want, inner)
        self.assertEqual(sum(n.startswith("zwo/") for n in inner), 2)
        self.assertEqual(sum(n.startswith("fit/") for n in inner), 2)
        for pdf in ("Plan.pdf", "How to import.pdf"):
            self.assertTrue(zf.read(f"Alex training plan/{pdf}").startswith(b"%PDF"))
        guide = zf.read("Alex training plan/HOW_TO_IMPORT.txt").decode()
        self.assertIn("Alex training plan", guide)
        self.assertNotIn("—", guide)

    def test_a_blank_name_gets_a_plain_folder(self):
        zf = zipfile.ZipFile(io.BytesIO(exporters.share_package_zip(self.rows(), "  ", 300)))
        self.assertTrue(zf.namelist()[0].startswith("Training plan/"))


# ── Steps built once and kept ─────────────────────────────────────────────────

class StepTests(Base):
    def test_saved_steps_are_reused_and_only_missing_ones_are_built(self):
        done = self.ride(D(1))
        q.save_workout_steps(done["id"], json.dumps(STEPS))
        todo = [self.ride(D(2)), self.ride(D(3))]
        seen = []
        with mock.patch.object(garmin_workouts, "build_steps", side_effect=lambda w: seen.append(w["id"]) or STEPS):
            ticks = []
            out = garmin_workouts.ensure_steps([q.get_workout(done["id"])] + todo,
                                               progress=lambda d, t: ticks.append((d, t)))
        self.assertEqual(sorted(seen), sorted(w["id"] for w in todo))
        self.assertEqual(ticks[-1], (2, 2))
        self.assertTrue(all(out[w["id"]] == STEPS for w in [done] + todo))
        self.assertTrue(all(garmin_workouts.saved_steps(q.get_workout(w["id"])) == STEPS for w in todo))
        with mock.patch.object(garmin_workouts, "build_steps", side_effect=AssertionError("built twice")):
            garmin_workouts.ensure_steps([q.get_workout(w["id"]) for w in todo])

    def test_one_failure_is_reported_and_the_rest_still_build(self):
        a, b = self.ride(D(1), name="Good"), self.ride(D(2), name="Bad")
        def build(w):
            if w["name"] == "Bad":
                raise garmin_workouts.WorkoutError("No steps came back for this workout.")
            return STEPS
        with mock.patch.object(garmin_workouts, "build_steps", side_effect=build):
            out = garmin_workouts.ensure_steps([a, b])
        self.assertEqual(out[a["id"]], STEPS)
        self.assertIn("No steps", out[b["id"]])
        self.assertIsNone(q.get_workout(b["id"])["structured_json"])

    def test_no_ftp_is_one_clear_error(self):
        q.set_setting("ftp_watts", "0")
        with self.assertRaises(garmin_workouts.WorkoutError):
            garmin_workouts.ensure_steps([self.ride(D(1))])

    def test_saving_steps_does_not_make_it_look_sent_to_garmin(self):
        w = self.ride(D(1))
        q.save_workout_steps(w["id"], json.dumps(STEPS))
        self.assertEqual(q.garmin_status(q.get_workout(w["id"])), "not_sent")

    def test_steps_are_cleared_when_what_they_came_from_changes(self):
        w = self.ride(D(1))
        q.save_workout_steps(w["id"], json.dumps(STEPS))
        q.update_workout(w["id"], {**q.get_workout(w["id"]), "completed": 1})     # marking done keeps them
        self.assertIsNotNone(q.get_workout(w["id"])["structured_json"])
        for change in ({"tss_planned": 90}, {"workout_type": "Threshold"}, {"description": "3x10"}, {"name": "New"}):
            q.save_workout_steps(w["id"], json.dumps(STEPS))
            q.update_workout(w["id"], {**q.get_workout(w["id"]), **change})
            with self.subTest(change):
                self.assertIsNone(q.get_workout(w["id"])["structured_json"])

    def test_the_prompt_sizes_rides_without_durations_from_tss(self):
        self.assertIn("size the\n  ride from the planned TSS", garmin_workouts.SYSTEM)


# ── intervals.icu ─────────────────────────────────────────────────────────────

class IntervalsTests(Base):
    def setUp(self):
        super().setUp()
        q.set_setting(intervals.KEY_SETTING, "secret-key")

    def test_the_key_is_sent_as_basic_auth_with_api_key_as_the_user(self):
        self.assertEqual(intervals._session().auth, ("API_KEY", "secret-key"))
        s = FakeSession({("GET", f"{intervals.API}/athlete/0"): Response(200, {"name": "Sam"})})
        self.assertEqual(intervals.check(session=s), "Sam")
        bad = FakeSession({("GET", f"{intervals.API}/athlete/0"): Response(401, {})})
        with self.assertRaises(intervals.IntervalsError) as cm:
            intervals.check(session=bad)
        self.assertIn("API key", str(cm.exception))

    def test_each_ride_is_a_dated_zwift_workout_with_our_id(self):
        e = intervals.event_payload(W, "<workout_file/>")
        self.assertEqual((e["category"], e["type"], e["start_date_local"]), ("WORKOUT", "Ride", f"{W['date']}T00:00:00"))
        self.assertEqual((e["external_id"], e["filename"]), ("cc-7", f"{W['date']}_Sweet_spot_3x15.zwo"))
        self.assertEqual(e["file_contents"], "<workout_file/>")

    def test_sync_upserts_in_chunks_and_removes_rides_gone_from_the_plan(self):
        rides = [self.ride(D(1 + i % 20), name=f"R{i}") for i in range(60)]
        gone = self.ride(D(5), name="Gone")
        outside = self.ride(D(40), name="Later")
        q.save_synced("intervals", [{"workout_id": gone["id"], "remote_id": "cc-x", "date": D(5)},
                                    {"workout_id": outside["id"], "remote_id": "cc-y", "date": D(40)}])
        s = FakeSession()
        out = intervals.sync([(w, STEPS) for w in rides], D(0), D(27), session=s)
        posts = [c for c in s.calls if c["method"] == "POST"]
        self.assertEqual([len(c["json"]) for c in posts], [50, 10])
        self.assertEqual(posts[0]["params"], {"upsert": "true"})
        self.assertTrue(posts[0]["url"].endswith("/athlete/0/events/bulk"))
        puts = [c for c in s.calls if c["method"] == "PUT"]
        self.assertEqual(puts[0]["json"], [{"external_id": f"cc-{gone['id']}"}])   # the one outside the range stays
        self.assertEqual(out, {"sent": 60, "removed": 1})
        synced = q.get_synced("intervals")
        self.assertNotIn(gone["id"], synced)
        self.assertIn(outside["id"], synced)
        self.assertEqual(len(synced), 61)

    def test_a_refusal_raises_and_records_nothing(self):
        s = FakeSession({("POST", intervals.API): Response(500, {}, "boom")})
        with self.assertRaises(intervals.IntervalsError):
            intervals.sync([(self.ride(D(1)), STEPS)], D(0), D(27), session=s)
        self.assertEqual(q.get_synced("intervals"), {})

    def test_remove_only_touches_rides_that_were_sent(self):
        a, b = self.ride(D(1)), self.ride(D(2))
        q.save_synced("intervals", [{"workout_id": a["id"], "remote_id": "cc", "date": D(1)}])
        s = FakeSession()
        intervals.remove([a["id"], b["id"]], session=s)
        self.assertEqual(s.calls[0]["json"], [{"external_id": f"cc-{a['id']}"}])
        self.assertEqual(q.get_synced("intervals"), {})
        s2 = FakeSession()
        intervals.remove([b["id"]], session=s2)
        self.assertEqual(s2.calls, [])


# ── TrainingPeaks calendar ────────────────────────────────────────────────────

def tp_session(created=None, listing=None, token_status=200):
    created = created if created is not None else {"workoutId": 555}
    return FakeSession({
        ("GET", f"{tp.API}/users/v3/token"): Response(token_status, {"token": {"access_token": "tok"}}),
        ("GET", f"{tp.API}/users/v3/user"): Response(200, {"user": {"userId": 42, "firstName": "Sam",
                                                                      "accountStatus": {"isPremium": True}}}),
        ("POST", f"{tp.API}/fitness/v6/athletes/42/workouts"): Response(200, created),
        ("GET", f"{tp.API}/fitness/v6/athletes/42/workouts/"): Response(200, listing or []),
    })


class TrainingPeaksTests(Base):
    def test_the_cookie_becomes_a_bearer_token(self):
        s = tp_session()
        c = tp.Client("Production_tpAuth=abc; other=1", session=s)
        self.assertEqual(s.calls[0]["headers"], {"Cookie": "Production_tpAuth=abc"})
        self.assertEqual(s.headers["Authorization"], "Bearer tok")
        self.assertEqual((c.user_id, c.name, c.premium), ("42", "Sam", True))

    def test_a_refused_cookie_says_to_paste_a_fresh_one(self):
        with self.assertRaises(tp.TPAuthError) as cm:
            tp.Client("abc", session=tp_session(token_status=401))
        self.assertIn("fresh", str(cm.exception))

    def test_steps_become_trainingpeaks_structure_in_percent_of_ftp(self):
        st = tp.to_tp_structure(STEPS + [{"kind": "interval", "minutes": 3, "low_pct": None, "high_pct": None}])
        self.assertEqual((st["primaryLengthMetric"], st["primaryIntensityMetric"]), ("duration", "percentOfFtp"))
        warm, rep, cool, free = st["structure"]
        self.assertEqual(warm["type"], "step")
        self.assertEqual(warm["steps"][0]["length"], {"value": 600, "unit": "second"})
        self.assertEqual(warm["steps"][0]["targets"], [{"minValue": 50, "maxValue": 65}])
        self.assertEqual((rep["type"], rep["length"]), ("repetition", {"value": 3, "unit": "repetition"}))
        self.assertEqual(len(rep["steps"]), 2)
        self.assertEqual(free["steps"][0]["targets"], [{"minValue": 40, "maxValue": 55}])

    def test_the_create_payload(self):
        p = tp.payload("42", W, STEPS)
        self.assertEqual((p["athleteId"], p["workoutDay"], p["workoutTypeValueId"], p["title"]),
                         ("42", W["date"], 2, "Sweet spot 3x15"))
        self.assertEqual((p["totalTimePlanned"], p["tssPlanned"]), (round(80 / 60, 3), 85))
        self.assertEqual(json.loads(p["structure"])["primaryIntensityMetric"], "percentOfFtp")

    def test_sync_creates_skips_unchanged_replaces_changed_and_removes_gone(self):
        a, b = self.ride(D(1), name="A"), self.ride(D(2), name="B")
        s = tp_session()
        out = tp.sync([(a, STEPS), (b, STEPS)], D(0), D(27), client=tp.Client("abc", session=s))
        self.assertEqual((out["sent"], out["unchanged"], out["removed"]), (2, 0, 0))
        self.assertEqual(q.get_synced("trainingpeaks")[a["id"]]["remote_id"], "555")

        s = tp_session(created={"workoutId": 777})
        moved = {**a, "date": D(4)}
        out = tp.sync([(moved, STEPS)], D(0), D(27), client=tp.Client("abc", session=s))
        deletes = [c["url"] for c in s.calls if c["method"] == "DELETE"]
        self.assertEqual(sorted(deletes), sorted([f"{tp.API}/fitness/v6/athletes/42/workouts/555"] * 2))  # moved A, gone B
        self.assertEqual((out["sent"], out["unchanged"], out["removed"]), (1, 0, 1))
        synced = q.get_synced("trainingpeaks")
        self.assertEqual((synced[a["id"]]["remote_id"], synced[a["id"]]["date"]), ("777", D(4)))
        self.assertNotIn(b["id"], synced)

        s = tp_session()
        out = tp.sync([(moved, STEPS)], D(0), D(27), client=tp.Client("abc", session=s))
        self.assertEqual((out["sent"], out["unchanged"]), (0, 1))
        self.assertFalse([c for c in s.calls if c["method"] in ("POST", "DELETE")])

    def test_the_new_id_is_found_on_the_calendar_when_create_does_not_say(self):
        a = self.ride(D(1), name="A")
        s = tp_session(created={}, listing=[{"workoutId": 9, "title": "A"}, {"workoutId": 12, "title": "A"},
                                            {"workoutId": 30, "title": "Other"}])
        tp.sync([(a, STEPS)], D(0), D(27), client=tp.Client("abc", session=s))
        self.assertEqual(q.get_synced("trainingpeaks")[a["id"]]["remote_id"], "12")

    def test_one_failure_is_reported_and_the_rest_still_go(self):
        a, b = self.ride(D(1), name="A"), self.ride(D(2), name="B")
        s = tp_session()
        s.routes[("POST", f"{tp.API}/fitness/v6/athletes/42/workouts")] = (
            lambda call: Response(400, {}, "nope") if call["json"]["title"] == "A" else Response(200, {"workoutId": 3}))
        out = tp.sync([(a, STEPS), (b, STEPS)], D(0), D(27), client=tp.Client("abc", session=s))
        self.assertEqual(out["sent"], 1)
        self.assertEqual(len(out["failed"]), 1)
        self.assertIn("A", out["failed"][0]["name"])

    def test_signing_out_stops_the_sync_but_keeps_what_was_sent(self):
        a, b = self.ride(D(1), name="A"), self.ride(D(2), name="B")
        s = tp_session()
        s.routes[("POST", f"{tp.API}/fitness/v6/athletes/42/workouts")] = (
            lambda call: Response(401, {}) if call["json"]["title"] == "B" else Response(200, {"workoutId": 3}))
        with self.assertRaises(tp.TPAuthError):
            tp.sync([(a, STEPS), (b, STEPS)], D(0), D(27), client=tp.Client("abc", session=s))
        self.assertEqual(list(q.get_synced("trainingpeaks")), [a["id"]])

    def test_it_is_off_until_turned_on(self):
        self.assertFalse(tp.is_enabled())
        q.set_setting(tp.COOKIE_SETTING, "abc")
        self.assertFalse(tp.is_enabled())
        q.set_setting(tp.ENABLED_SETTING, "1")
        self.assertTrue(tp.is_enabled())


# ── Removing a ride removes it everywhere ─────────────────────────────────────

class RemovalTests(Base):
    def test_the_coach_removing_a_ride_passes_it_on(self):
        import coach_tools
        import plan_changes
        w = self.ride(D(3))
        out = []
        coach_tools._propose_changes({"changes": [{"target": "ride", "id": w["id"], "action": "remove",
                                                   "reason": "x"}]}, out)
        with mock.patch("garmin_workouts.remove_from_garmin"), mock.patch("sync.remove_everywhere") as rm:
            plan_changes.apply_changes(out)
        rm.assert_called_once_with([w["id"]])

    def test_a_program_replacing_rides_passes_them_on(self):
        import programs
        from tests.test_programs import sample, MONDAY
        old = self.ride((MONDAY + timedelta(days=1)).isoformat())
        prog = programs.save_draft(sample())
        with mock.patch("garmin_workouts.remove_from_garmin"), mock.patch("sync.remove_everywhere") as rm:
            programs.apply(prog["id"], replace_existing=True)
        rm.assert_called_once_with([old["id"]])

    def test_remove_everywhere_asks_each_service_and_never_raises(self):
        import sync
        with mock.patch.object(intervals, "remove", side_effect=RuntimeError("down")) as iv, \
                mock.patch.object(tp, "remove") as tpr:
            sync.remove_everywhere([1, None, 2])
        iv.assert_called_once_with([1, 2])
        tpr.assert_called_once_with([1, 2])


class FailureTests(unittest.TestCase):
    def test_one_reason_is_said_once(self):
        from components import plan_export as pe
        rides = [{"id": i, "date": "2026-10-0%d" % (i + 1), "name": f"R{i}", "structured_json": None} for i in range(3)]
        errors = {0: "Bad key.", 1: "Bad key.", 2: "Too long."}
        self.assertEqual(pe.group_failures(rides, errors),
                         {"Bad key.": ["Oct 1 R0", "Oct 2 R1"], "Too long.": ["Oct 3 R2"]})


class RangeTests(unittest.TestCase):
    def test_ranges(self):
        from components import plan_export as pe
        today = date(2026, 10, 7)                                    # a Wednesday
        self.assertEqual(pe.date_range(pe.WEEK, today, None), ("2026-10-07", "2026-10-11"))
        self.assertEqual(pe.date_range(pe.FOUR, today, None), ("2026-10-07", "2026-11-03"))
        self.assertEqual(pe.date_range(pe.TWELVE, today, None)[1], "2026-12-29")
        prog = {"start_date": "2026-10-05", "end_date": "2027-01-03"}
        self.assertEqual(pe.date_range(pe.PROGRAM, today, prog), ("2026-10-07", "2027-01-03"))
        self.assertEqual(pe.date_range(pe.CUSTOM, today, None, (date(2026, 10, 1), date(2026, 10, 20))),
                         ("2026-10-07", "2026-10-20"))


if __name__ == "__main__":
    unittest.main()
