"""hrTSS: TRIMP scaled so an hour at threshold heart rate is 100, used for rides without power
and to fill power dropouts. Run with venv/bin/python -m unittest tests.test_hr_tss -v"""
import math
from datetime import date, timedelta
from unittest import mock

from auth import garmin as garmin_auth
from db import queries as q
from metrics import streams as sm
from metrics.tss import hr_tss, hr_tss_seconds, k_for, label, ride_tss, robust_max_hr, stream_tss
from tests.test_manual_tss import Base, ride

TODAY = date.today()
SAM = {"rest": 45, "max": 197, "k": 1.92}


def trimp(minutes, hr, p):
    hrr = (hr - p["rest"]) / (p["max"] - p["rest"])
    return minutes * hrr * 0.64 * math.exp(p["k"] * hrr)


class FormulaTests(Base):
    def test_an_hour_at_threshold_is_100(self):
        self.assertAlmostEqual(hr_tss(3600, 170, 170, SAM), 100)

    def test_matches_banister_trimp_scaled_to_threshold(self):
        expected = trimp(90, 150, SAM) / trimp(60, 170, SAM) * 100
        self.assertAlmostEqual(hr_tss(5400, 150, 170, SAM), expected)
        self.assertAlmostEqual(hr_tss(3600, 150, 170, SAM), 65.2, delta=0.1)

    def test_hard_minutes_count_for_more_than_easy_ones(self):
        steady = hr_tss_seconds([150] * 3600, 170, SAM)
        mixed = hr_tss_seconds([130] * 1800 + [170] * 1800, 170, SAM)   # same average
        self.assertGreater(mixed, steady)

    def test_women_use_the_lower_constant(self):
        self.assertEqual(k_for("woman"), 1.67)
        self.assertEqual(k_for("man"), 1.92)
        self.assertAlmostEqual(k_for("unspecified"), 1.795)

    def test_without_resting_and_max_it_falls_back(self):
        self.assertAlmostEqual(hr_tss(3600, 150, 170, {"rest": None, "max": None}), (150 / 170) ** 2 * 100)

    def test_a_one_off_spike_does_not_set_max_hr(self):
        self.assertEqual(robust_max_hr([208, 197, 193, 193, 190]), 197)
        self.assertEqual(robust_max_hr([180]), 180)

    def test_labels(self):
        self.assertEqual(label("hr"), "hrTSS")
        self.assertEqual(label("mixed"), "TSS + hrTSS")
        self.assertEqual(label("power"), "TSS")
        self.assertEqual(label(None), "TSS")


class StreamTests(Base):
    def test_full_power_keeps_the_summary_number(self):
        self.assertIsNone(stream_tss({"power": [250] * 3600, "hr": [150] * 3600}, 250, 170, SAM))

    def test_no_power_scores_every_second_from_heart_rate(self):
        tss, source = stream_tss({"hr": [170] * 3600}, 250, 170, SAM)
        self.assertEqual(source, "hr")
        self.assertAlmostEqual(tss, 100)

    def test_a_dropout_is_filled_with_hrtss(self):
        power = [250] * 1800 + [None] * 1800
        tss, source = stream_tss({"power": power, "hr": [170] * 3600}, 250, 170, SAM)
        self.assertEqual(source, "mixed")
        self.assertAlmostEqual(tss, 100, delta=0.5)   # 30 min at FTP + 30 min at LTHR

    def test_coasting_zeros_are_not_a_dropout(self):
        power = [250] * 3000 + [0] * 600
        self.assertIsNone(stream_tss({"power": power, "hr": [150] * 3600}, 250, 170, SAM))

    def test_short_gaps_are_ignored(self):
        power = [250] * 1800 + [None] * 30 + [250] * 1770
        self.assertIsNone(stream_tss({"power": power, "hr": [150] * 3600}, 250, 170, SAM))

    def test_ride_analysis_numbers_use_hrtss_without_power(self):
        n = sm.numbers_from_streams({"hr": [170] * 3600}, 250, 170, SAM)
        self.assertEqual(n["tss_source"], "hr")
        self.assertAlmostEqual(n["tss"], 100)


class StoredRideTests(Base):
    def setUp(self):
        super().setUp()
        q.set_setting("lthr", "170")
        q.set_setting("resting_hr_manual", "45")
        q.set_setting("max_hr_manual", "197")
        q.set_setting("gender", "man")

    def test_a_ride_without_power_is_stored_as_hrtss(self):
        aid = q.upsert_activity(ride("hr1", normalized_power=None, avg_power_watts=None, avg_hr=150, tss=1))
        q.recalculate_all_tss()
        a = q.get_activity(aid)
        self.assertEqual(a["tss_source"], "hr")
        self.assertAlmostEqual(a["tss"], 65.2, delta=0.1)

    def test_saved_streams_with_a_dropout_rescore_the_ride(self):
        aid = q.upsert_activity(ride("drop", normalized_power=250, avg_hr=170, tss=1, duration_seconds=3600))
        q.save_streams(aid, {"power": [250] * 1800 + [None] * 1800, "hr": [170] * 3600})
        self.assertTrue(q.rescore_from_streams(aid))
        a = q.get_activity(aid)
        self.assertEqual(a["tss_source"], "mixed")
        self.assertAlmostEqual(a["tss"], 100, delta=0.5)

    def test_a_hand_set_tss_is_not_rescored(self):
        aid = q.upsert_activity(ride("lock", normalized_power=None, avg_hr=150, tss=1))
        q.set_activity_tss(aid, 77)
        q.save_streams(aid, {"hr": [170] * 3600})
        self.assertFalse(q.rescore_from_streams(aid))
        self.assertEqual(q.get_activity(aid)["tss_source"], "manual")

    def test_garmin_sync_checks_the_ride_file_for_dropouts(self):
        act = {"activityType": {"typeKey": "road_biking"}, "activityId": 5,
               "startTimeLocal": f"{TODAY - timedelta(days=1)} 08:00:00", "duration": 3600,
               "normPower": 250, "averageHR": 170}
        api = mock.Mock()
        api.get_activities_by_date.return_value = [act]
        streams = {"power": [250] * 1800 + [None] * 1800, "hr": [170] * 3600}
        with mock.patch.object(garmin_auth, "_ride_file", return_value=b"fit"), \
             mock.patch.object(garmin_auth, "_hr_peaks", return_value={}), \
             mock.patch("metrics.streams.from_fit", return_value=streams):
            garmin_auth._sync_rides(api, 7)
        a = q.get_activities(days_back=7)[0]
        self.assertEqual(a["tss_source"], "mixed")
        self.assertIsNotNone(q.get_streams(a["id"]))

    def test_garmin_rides_with_full_power_keep_garmin_numbers_and_no_stored_data(self):
        act = {"activityType": {"typeKey": "road_biking"}, "activityId": 6,
               "startTimeLocal": f"{TODAY - timedelta(days=1)} 08:00:00", "duration": 3600,
               "normPower": 250, "averageHR": 150}
        api = mock.Mock()
        api.get_activities_by_date.return_value = [act]
        with mock.patch.object(garmin_auth, "_ride_file", return_value=b"fit"), \
             mock.patch.object(garmin_auth, "_hr_peaks", return_value={}), \
             mock.patch("metrics.streams.from_fit", return_value={"power": [250] * 3600, "hr": [150] * 3600}):
            garmin_auth._sync_rides(api, 7)
        a = q.get_activities(days_back=7)[0]
        self.assertEqual(a["tss_source"], "power")
        self.assertIsNone(q.get_streams(a["id"]))


class DeviceNumbersTests(Base):
    def test_strava_rides_take_garmins_normalized_power(self):
        aid = q.upsert_activity(ride("strava_1", source="strava", normalized_power=240, tss=1,
                                     date=(TODAY - timedelta(days=40)).isoformat()))
        q.recalculate_all_tss()
        before = q.get_activity(aid)["tss"]
        act = {"activityType": {"typeKey": "road_biking"}, "activityId": 77,
               "startTimeLocal": f"{TODAY - timedelta(days=40)} 08:00:00", "duration": 3600,
               "movingDuration": 3600, "elapsedDuration": 3700, "distance": 30000,
               "normPower": 250, "averageHR": 140}
        api = mock.Mock()
        api.get_activities_by_date.return_value = [act]
        with mock.patch.object(garmin_auth, "_client", return_value=api), \
             mock.patch.object(garmin_auth, "_hr_peaks", return_value={}):
            updated, seen = garmin_auth.backfill_peaks(days_back=60)
        a = q.get_activity(aid)
        self.assertEqual((a["normalized_power"], a["timer_seconds"]), (250, 3600))
        self.assertAlmostEqual(a["tss"], 100, places=0)
        self.assertGreater(a["tss"], before)
        self.assertEqual(len(q.get_activities(days_back=60)), 1)        # no ride added

    def test_a_hand_corrected_ride_keeps_its_numbers(self):
        aid = q.upsert_activity(ride("strava_2", source="strava", normalized_power=240))
        q.update_activity_details(aid, {"normalized_power": 230})
        self.assertFalse(q.apply_device_numbers(aid, 250, 3600))
        self.assertEqual(q.get_activity(aid)["normalized_power"], 230)
