"""Second by second ride data and the ride analysis. Run with
venv/bin/python -m unittest tests.test_streams -v"""
import os
import tempfile
import unittest
from unittest import mock

from auth import ride_data
from db import schema, queries as q
from metrics import streams as sm


def recs(n, power=200, hr=140, cad=90, skip=()):
    return [{"t": i, "power": power, "hr": hr, "cad": cad, "alt": 100 + i * 0.1, "speed": 8.0}
            for i in range(n) if i not in skip]


class BuildTests(unittest.TestCase):
    def test_one_value_per_second_and_channels_present(self):
        s = sm.from_records(recs(120))
        self.assertEqual({k: len(v) for k, v in s.items()}, {k: 120 for k in ("power", "hr", "cad", "speed", "alt")})
        self.assertEqual(s["power"][5], 200)
        self.assertIsNone(sm.from_records([]))
        self.assertIsNone(sm.from_records([{"t": 1}]))                      # no channels at all
        self.assertNotIn("power", sm.from_records([{"t": i, "hr": 100} for i in range(30)]))

    def test_short_gaps_are_filled_and_long_ones_left_empty(self):
        s = sm.from_records(recs(120, skip=set(range(10, 15)) | set(range(40, 70))))
        self.assertEqual(s["power"][10:15], [200] * 5)                      # 5 s gap repeats the last value
        self.assertEqual(s["power"][40:70], [None] * 30)                    # 30 s gap stays empty
        self.assertEqual(s["power"][70], 200)

    def test_unsorted_duplicate_and_bad_values(self):
        s = sm.from_records([{"t": 2, "power": 300}, {"t": 0, "power": 100}, {"t": 1, "power": "bad"},
                             {"t": 1, "power": float("nan")}, {"t": -5, "power": 9}, {"t": 3, "power": 150}])
        self.assertEqual(s["power"], [100, 100, 300, 150])

    def test_from_strava(self):
        data = {"time": {"data": [0, 1, 2, 3]}, "watts": {"data": [100, 110, 120, 130]},
                "heartrate": {"data": [120, 121, 122, 123]}, "velocity_smooth": {"data": [5, 5, 5, 5]}}
        s = sm.from_strava(data)
        self.assertEqual(s["power"], [100, 110, 120, 130])
        self.assertEqual(s["hr"][3], 123)
        self.assertEqual(s["speed"][0], 5.0)
        self.assertIsNone(sm.from_strava({}))
        self.assertIsNone(sm.from_strava({"watts": {"data": [1]}}))        # no time axis


class MathTests(unittest.TestCase):
    def test_smooth_keeps_gaps_and_averages(self):
        self.assertEqual(sm.smooth([1, 2, 3], 1), [1, 2, 3])
        out = sm.smooth([1, 2, 3, None, 5, 6], 3)
        self.assertEqual(out[:3], [1.5, 2.0, 2.5])
        self.assertIsNone(out[3])
        self.assertEqual(sm.smooth([], 5), [])

    def test_downsample(self):
        xs, ys = sm.downsample(list(range(10)), 100)
        self.assertEqual((xs, ys), (list(range(10)), list(range(10))))
        xs, ys = sm.downsample([1.0] * 5000, 1000)
        self.assertLessEqual(len(xs), 1000)
        self.assertTrue(all(abs(y - 1.0) < 1e-9 for y in ys))
        xs, ys = sm.downsample([None] * 3000, 1000)
        self.assertTrue(all(y is None for y in ys))

    def test_zone_seconds_match_the_app_zones(self):
        secs = sm.power_zone_seconds([100, 150, 200, 250, 300, 400, None], 250)
        self.assertEqual(secs, [1, 1, 1, 1, 1, 0, 1])
        self.assertEqual(sm.power_zone_seconds([200], 0), [0.0] * 7)
        self.assertEqual(sum(sm.hr_zone_seconds([100, 140, 160, 175], 165)), 4)

    def test_normalized_power(self):
        self.assertAlmostEqual(sm.normalized_power([200] * 600), 200.0, places=3)
        self.assertIsNone(sm.normalized_power([200] * 10))
        steady = sm.normalized_power([200] * 600)
        surgy = sm.normalized_power(([100] * 30 + [300] * 30) * 10)
        self.assertGreater(surgy, 200)                                       # same average, higher NP
        self.assertGreater(surgy, steady)

    def test_decoupling(self):
        steady = sm.decoupling([200] * 4000, [140] * 4000)
        self.assertAlmostEqual(steady, 0.0, places=6)
        drift = sm.decoupling([200] * 4000, [140] * 2000 + [154] * 2000)
        self.assertAlmostEqual(drift, (200 / 140 - 200 / 154) / (200 / 140) * 100, places=6)
        self.assertGreater(drift, 5)
        self.assertIsNone(sm.decoupling([200] * 600, [140] * 600))           # too short
        self.assertIsNone(sm.decoupling([200] * 4000, []))

    def test_ride_peaks(self):
        power = [100] * 600 + [400] * 60 + [100] * 600
        peaks = sm.ride_peaks(power, [5, 60, 300])
        self.assertEqual(peaks[5], 400.0)
        self.assertEqual(peaks[60], 400.0)
        self.assertAlmostEqual(peaks[300], (400 * 60 + 100 * 240) / 300, places=1)

    def test_find_efforts(self):
        ride = [150] * 600 + [260] * 480 + [100] * 300 + [265] * 300 + [120] * 200
        efforts = sm.find_efforts(ride, 250, [140] * len(ride))
        self.assertEqual(len(efforts), 2)
        self.assertAlmostEqual(efforts[0]["start"], 600, delta=20)
        self.assertGreater(efforts[0]["seconds"], 450)
        self.assertAlmostEqual(efforts[0]["avg_power"], 260, delta=3)
        self.assertEqual(efforts[0]["avg_hr"], 140)
        self.assertEqual(sm.find_efforts([100] * 900, 250), [])
        self.assertEqual(sm.find_efforts([300] * 100, 250), [])               # too short
        self.assertEqual(sm.find_efforts([300] * 900, 0), [])
        # a 10 second dip does not end an effort
        dip = [260] * 300 + [100] * 10 + [260] * 300
        self.assertEqual(len(sm.find_efforts(dip, 250)), 1)

    def test_elapsed_label(self):
        self.assertEqual((sm.elapsed_label(65), sm.elapsed_label(3725)), ("1:05", "1:02:05"))


class SummaryTests(unittest.TestCase):
    def test_stored_numbers_win_and_gaps_are_filled_from_the_streams(self):
        from components import ride_analysis as ra
        act = {"duration_seconds": 3600, "distance_meters": 30000, "elevation_gain_meters": 300, "tss": 60,
               "avg_power_watts": None, "normalized_power": None, "if_value": 0.7, "avg_hr": 150, "max_hr": None}
        streams = sm.from_records(recs(3600, power=200, hr=140))
        n = ra.summary_numbers(act, streams)
        self.assertAlmostEqual(n["avg_w"], 200)
        self.assertAlmostEqual(n["np"], 200, delta=1)
        self.assertEqual(n["avg_hr"], 150)                                    # the stored value wins
        self.assertEqual(n["max_hr"], 140)
        self.assertAlmostEqual(n["kj"], 720, delta=1)
        self.assertAlmostEqual(n["vi"], 1.0, delta=0.01)
        bare = ra.summary_numbers({"duration_seconds": None}, None)
        self.assertIsNone(bare["avg_w"])
        self.assertIsNone(bare["kj"])


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        schema.run_migrations()

    def activity(self, source="garmin", ext="garmin_555"):
        return q.upsert_activity({
            "source": source, "external_id": ext, "date": "2026-09-02", "name": "Ride",
            "sport_type": "ride", "duration_seconds": 3600, "elapsed_seconds": 3700,
            "distance_meters": 30000, "elevation_gain_meters": 300, "avg_power_watts": 200, "avg_hr": 140,
            "max_hr": 170, "normalized_power": 210, "tss": 60, "if_value": 0.7, "raw_json": "{}"})

    def test_ids_from_the_external_id(self):
        self.assertEqual(ride_data.garmin_id({"external_id": "garmin_123", "source": "garmin"}), "123")
        self.assertIsNone(ride_data.garmin_id({"external_id": "strava_9", "source": "strava", "raw_json": "{}"}))
        self.assertEqual(ride_data.strava_id({"external_id": "strava_9"}), "9")
        self.assertIsNone(ride_data.strava_id({"external_id": "garmin_9"}))
        self.assertIsNone(ride_data.strava_id({"external_id": "strava_x"}))

    def test_fetches_once_then_uses_the_kept_copy(self):
        aid = self.activity()
        data = sm.from_records(recs(60))
        with mock.patch.object(ride_data, "_from_garmin", return_value=data) as g, \
                mock.patch.object(ride_data, "_from_strava", return_value=None):
            g.__name__ = "_from_garmin"
            first, note = ride_data.load_streams(aid)
            second, _ = ride_data.load_streams(aid)
        self.assertEqual((first, note), (data, ""))
        self.assertEqual(second, data)
        self.assertEqual(g.call_count, 1)                                     # the second call came from the database

    def test_strava_rides_try_strava_first_and_fall_back_to_garmin(self):
        aid = self.activity("strava", "strava_77")
        order = []
        def strava(a):
            order.append("strava")
            return None
        def garmin(a):
            order.append("garmin")
            return sm.from_records(recs(60))
        strava.__name__, garmin.__name__ = "_from_strava", "_from_garmin"
        with mock.patch.object(ride_data, "_from_strava", strava), mock.patch.object(ride_data, "_from_garmin", garmin):
            data, _ = ride_data.load_streams(aid)
        self.assertEqual(order, ["strava", "garmin"])
        self.assertIsNotNone(data)

    def test_failures_and_missing_data_give_a_plain_message(self):
        aid = self.activity()
        def boom(a):
            raise RuntimeError("Garmin is limiting requests")
        boom.__name__ = "_from_garmin"
        with mock.patch.object(ride_data, "_from_garmin", boom), mock.patch.object(ride_data, "_from_strava", lambda a: None):
            data, note = ride_data.load_streams(aid)
        self.assertIsNone(data)
        self.assertIn("Couldn't load", note)
        none = lambda a: None
        with mock.patch.object(ride_data, "_from_garmin", none), mock.patch.object(ride_data, "_from_strava", none):
            data, note = ride_data.load_streams(aid)
        self.assertIn("No second by second data", note)
        self.assertEqual(ride_data.load_streams(9999)[1], "That ride is no longer in the app.")

    def test_streams_round_trip_and_follow_a_merged_ride(self):
        aid = self.activity()
        data = sm.from_records(recs(60))
        q.save_streams(aid, data, "garmin")
        self.assertEqual(q.get_streams(aid), data)
        q.save_streams(None, data)                                            # no ride, nothing stored
        self.assertIsNone(q.get_streams(9999))


if __name__ == "__main__":
    unittest.main()
