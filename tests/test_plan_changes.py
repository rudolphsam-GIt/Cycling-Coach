"""The coach changing the plan: tool validation, applying changes, strength removal.
Run with venv/bin/python -m unittest tests.test_plan_changes -v"""
import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

import coach_tools
import plan_changes as pc
from components import coach_ui
from db import schema, queries as q

TODAY = date.today()
D = lambda n: (TODAY + timedelta(days=n)).isoformat()
EX = [{"name": "Squat", "sets": 3, "reps": "6", "intensity": "RPE 7"}]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(schema, "DB_PATH", os.path.join(self.tmp.name, "t.db"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        schema.run_migrations()
        self.removed = []
        g = mock.patch("garmin_workouts.remove_from_garmin", self.removed.append)
        g.start()
        self.addCleanup(g.stop)

    def ride(self, day, name="Threshold", tss=90, **kw):
        return q.add_workout({"date": day, "name": name, "workout_type": "Threshold", "description": "4x8",
                              "structured_json": None, "tss_planned": tss, "notes": "",
                              "purpose": "Raise threshold", "feel": "7 out of 10", **kw})

    def strength(self, day, name="Lower body", completed=0):
        return q.add_strength_session({"date": day, "plan_week": 1, "exercises_json": json.dumps(EX),
                                       "duration_minutes": 45, "completed": completed,
                                       "notes": f"{name} | Planned by AI Coach", "purpose": "Leg strength"})

    def propose(self, changes):
        out = []
        coach_tools._propose_changes({"changes": changes}, out)
        return out


class ValidationTests(Base):
    def test_a_valid_move_update_and_remove(self):
        a, b, c = self.ride(D(3)), self.ride(D(4), "VO2"), self.ride(D(5), "Long")
        out = self.propose([
            {"target": "ride", "id": a, "action": "move", "new_date": D(6), "reason": "Travelling"},
            {"target": "ride", "id": b, "action": "update", "tss_planned": 60, "name": "Easier VO2", "reason": "Tired"},
            {"target": "ride", "id": c, "action": "remove", "reason": "Skipping"}])
        self.assertEqual([x["action"] for x in out], ["move", "update", "remove"])
        self.assertEqual(out[0]["new_date"], D(6))
        self.assertEqual(out[1]["fields"], {"name": "Easier VO2", "tss_planned": 60.0})
        self.assertEqual(out[1]["before"]["tss_planned"], 90)
        self.assertEqual(out[2]["name"], "Long")
        self.assertTrue(all(x["kind"] == "change" for x in out))

    def test_nothing_is_written_while_proposing(self):
        wid = self.ride(D(3))
        self.propose([{"target": "ride", "id": wid, "action": "remove", "reason": "x"}])
        self.assertIsNotNone(q.get_workout(wid))

    def test_done_items_cannot_change(self):
        done = self.ride(D(3))
        q.update_workout(done, {**q.get_workout(done), "completed": 1})
        s_done = self.strength(D(3), completed=1)
        for target, wid in (("ride", done), ("strength", s_done)):
            with self.assertRaises(coach_tools.ToolInputError, msg=(target, wid)):
                self.propose([{"target": target, "id": wid, "action": "remove", "reason": "x"}])

    def test_a_skipped_workout_can_be_moved_and_edited_by_the_coach_like_on_the_calendar(self):
        skipped = self.ride(D(-2))
        out = self.propose([{"target": "ride", "id": skipped, "action": "move", "new_date": D(2), "reason": "Do it later"}])
        self.assertEqual(out[0]["new_date"], D(2))
        done = pc.apply_changes(out)
        self.assertEqual((done["moved"], q.get_workout(skipped)["date"]), (1, D(2)))
        other = self.ride(D(-3))
        out = self.propose([{"target": "ride", "id": other, "action": "update", "tss_planned": 40, "reason": "Easier"}])
        self.assertEqual(out[0]["fields"], {"tss_planned": 40.0})

    def test_bad_input_is_rejected_with_a_helpful_message(self):
        wid = self.ride(D(3))
        bad = [
            {"target": "ride", "id": 9999, "action": "remove", "reason": "x"},                 # unknown id
            {"target": "ride", "id": "abc", "action": "remove", "reason": "x"},
            {"target": "other", "id": wid, "action": "remove", "reason": "x"},
            {"target": "ride", "id": wid, "action": "delete", "reason": "x"},
            {"target": "ride", "id": wid, "action": "remove"},                                  # no reason
            {"target": "ride", "id": wid, "action": "move", "reason": "x"},                     # no new_date
            {"target": "ride", "id": wid, "action": "move", "new_date": D(3), "reason": "x"},   # same day
            {"target": "ride", "id": wid, "action": "move", "new_date": D(-1), "reason": "x"},  # the past
            {"target": "ride", "id": wid, "action": "move", "new_date": "soon", "reason": "x"},
            {"target": "ride", "id": wid, "action": "update", "reason": "x"},                   # nothing to change
            {"target": "ride", "id": wid, "action": "update", "tss_planned": 900, "reason": "x"},
            {"target": "ride", "id": wid, "action": "update", "workout_type": "Nope", "reason": "x"},
            {"target": "ride", "id": wid, "action": "remove", "name": "x", "reason": "x"},      # remove takes nothing else
            {"target": "strength", "id": wid, "action": "remove", "reason": "x"},               # id is a ride, not strength
        ]
        for change in bad:
            with self.assertRaises(coach_tools.ToolInputError, msg=change):
                self.propose([change])
        with self.assertRaises(coach_tools.ToolInputError):
            self.propose([])
        with self.assertRaises(coach_tools.ToolInputError):
            self.propose([{"target": "ride", "id": wid, "action": "remove", "reason": "a"},
                          {"target": "ride", "id": wid, "action": "move", "new_date": D(9), "reason": "b"}])

    def test_strength_updates_are_checked(self):
        sid = self.strength(D(3))
        ok = self.propose([{"target": "strength", "id": sid, "action": "update", "duration_minutes": 30,
                            "exercises": EX, "reason": "Short on time"}])
        self.assertEqual(ok[0]["fields"]["duration_minutes"], 30)
        for fields in ({"duration_minutes": 2}, {"exercises": []}, {"exercises": [{"name": "Squat"}]},
                       {"tss_planned": 50}):                       # tss isn't a strength field, so nothing to change
            with self.assertRaises(coach_tools.ToolInputError, msg=fields):
                self.propose([{"target": "strength", "id": sid, "action": "update", "reason": "x", **fields}])

    def test_lookup_tools_return_ids_and_strength(self):
        wid, sid = self.ride(D(3)), self.strength(D(4), "Upper")
        rides = json.loads(coach_tools.run_tool("get_planned_workouts", {"start_date": D(0), "end_date": D(10)}, []))
        self.assertEqual((rides[0]["id"], rides[0]["purpose"]), (wid, "Raise threshold"))
        sessions = json.loads(coach_tools.run_tool("get_planned_strength", {"start_date": D(0), "end_date": D(10)}, []))
        self.assertEqual((sessions[0]["id"], sessions[0]["name"], sessions[0]["done"]), (sid, "Upper", False))
        self.assertIn("Squat 3x6 RPE 7", sessions[0]["exercises"])
        out = []
        msg = coach_tools.run_tool("propose_plan_changes", {"changes": [
            {"target": "ride", "id": wid, "action": "remove", "reason": "x"}]}, out)
        self.assertIn("Nothing has changed", msg)
        self.assertEqual(len(out), 1)

    def test_the_tools_are_registered(self):
        names = {t["name"] for t in coach_tools.TOOLS}
        self.assertTrue({"get_planned_strength", "propose_plan_changes"} <= names)
        self.assertIn("propose_plan_changes", coach_tools.STATUS_LABELS)


class ApplyTests(Base):
    def apply(self, changes):
        return pc.apply_changes([pc.validate_change(c) for c in changes])

    def test_move_update_and_remove_a_ride(self):
        a, b, c = self.ride(D(3)), self.ride(D(4), "VO2"), self.ride(D(5), "Long")
        q.set_workout_garmin(a, "g1", "s1", "[]", "2026-10-01T00:00:00")
        done = self.apply([
            {"target": "ride", "id": a, "action": "move", "new_date": D(6), "reason": "x"},
            {"target": "ride", "id": b, "action": "update", "tss_planned": 60, "feel": "5 out of 10", "reason": "x"},
            {"target": "ride", "id": c, "action": "remove", "reason": "x"}])
        self.assertEqual((done["moved"], done["updated"], done["removed"], done["skipped"]), (1, 1, 1, []))
        self.assertEqual(q.get_workout(a)["date"], D(6))
        self.assertIsNone(q.get_workout(a)["garmin_workout_id"])
        self.assertEqual([w["garmin_workout_id"] for w in self.removed if w.get("garmin_workout_id")],
                         ["g1"])                                            # the old Garmin copy
        w = q.get_workout(b)
        self.assertEqual((w["tss_planned"], w["feel"], w["purpose"], w["name"]), (60, "5 out of 10", "Raise threshold", "VO2"))
        self.assertIsNone(q.get_workout(c))
        self.assertEqual(done["first"], D(4))

    def test_update_and_move_together(self):
        a = self.ride(D(3))
        done = self.apply([{"target": "ride", "id": a, "action": "update", "name": "Easy spin",
                            "new_date": D(7), "reason": "x"}])
        self.assertEqual(done["updated"], 1)
        w = q.get_workout(a)
        self.assertEqual((w["name"], w["date"]), ("Easy spin", D(7)))

    def test_strength_move_update_and_remove(self):
        a, b, c = self.strength(D(3)), self.strength(D(4), "Upper"), self.strength(D(5), "Core")
        done = self.apply([
            {"target": "strength", "id": a, "action": "move", "new_date": D(8), "reason": "x"},
            {"target": "strength", "id": b, "action": "update", "name": "Upper light", "duration_minutes": 30,
             "reason": "x"},
            {"target": "strength", "id": c, "action": "remove", "reason": "x"}])
        self.assertEqual((done["moved"], done["updated"], done["removed"]), (1, 1, 1))
        self.assertEqual(q.get_strength_session(a)["date"], D(8))
        row = q.get_strength_session(b)
        self.assertEqual((row["duration_minutes"], row["notes"]), (30, "Upper light | Planned by AI Coach"))
        self.assertEqual(row["purpose"], "Leg strength")                   # untouched fields stay
        self.assertIsNone(q.get_strength_session(c))
        self.assertEqual([w for w in self.removed if w.get("garmin_workout_id")], [])   # strength never touches Garmin

    def test_changes_are_checked_again_when_applied(self):
        a, b = self.ride(D(3)), self.ride(D(4), "VO2")
        changes = [pc.validate_change({"target": "ride", "id": x, "action": "remove", "reason": "x"})
                   for x in (a, b)]
        q.delete_workout(a)                                                 # gone since the proposal
        q.update_workout(b, {**q.get_workout(b), "completed": 1})           # done since the proposal
        out = pc.apply_changes(changes)
        self.assertEqual(out["removed"], 0)
        self.assertEqual(len(out["skipped"]), 2)
        self.assertIsNotNone(q.get_workout(b))                              # the done ride is untouched

    def test_one_bad_change_does_not_block_the_rest(self):
        a, b = self.ride(D(3)), self.ride(D(4), "VO2")
        changes = [pc.validate_change({"target": "ride", "id": x, "action": "remove", "reason": "x"}) for x in (a, b)]
        q.delete_workout(a)
        out = pc.apply_changes(changes)
        self.assertEqual((out["removed"], len(out["skipped"])), (1, 1))
        self.assertIsNone(q.get_workout(b))

    def test_descriptions_read_well(self):
        a = self.ride(D(3))
        text = lambda c: pc.describe(pc.validate_change(c))
        self.assertIn("Move workout Threshold from", text({"target": "ride", "id": a, "action": "move",
                                                           "new_date": D(6), "reason": "x"}))
        self.assertIn("Remove workout Threshold", text({"target": "ride", "id": a, "action": "remove", "reason": "x"}))
        self.assertIn("TSS 90 to 60", text({"target": "ride", "id": a, "action": "update", "tss_planned": 60,
                                             "reason": "x"}))


class StrengthRemovalTests(Base):
    def test_delete_planned_and_logged_sessions(self):
        planned, logged = self.strength(D(3)), self.strength(D(-3), completed=1)
        self.assertEqual(q.delete_strength_session(planned)["id"], planned)
        self.assertIsNone(q.get_strength_session(planned))
        self.assertIsNotNone(q.delete_strength_session(logged))              # a past logged session too
        self.assertIsNone(q.delete_strength_session(planned))                # already gone, no error

    def test_update_strength_keeps_the_planned_marker(self):
        sid = self.strength(D(3))
        before = q.update_strength_session(sid, name="Heavy legs")
        self.assertEqual(before["notes"], "Lower body | Planned by AI Coach")
        self.assertEqual(q.get_strength_session(sid)["notes"], "Heavy legs | Planned by AI Coach")
        self.assertIsNone(q.update_strength_session(9999, name="x"))


class MergeTests(unittest.TestCase):
    def change(self, wid, action="remove", day="2026-10-10"):
        return {"kind": "change", "target": "ride", "id": wid, "action": action, "date": day, "name": "x",
                "reason": "r", "new_date": None, "fields": {}, "before": {}}

    def test_a_new_change_to_the_same_item_replaces_the_old_one(self):
        merged = coach_ui.merge_proposals([self.change(1, "remove"), self.change(2)],
                                          [self.change(1, "move")])
        self.assertEqual(sorted((c["id"], c["action"]) for c in merged), [(1, "move"), (2, "remove")])

    def test_changes_and_new_workouts_live_side_by_side(self):
        new = {"kind": "ride", "date": "2026-10-10", "name": "Easy"}
        merged = coach_ui.merge_proposals([self.change(1)], [new])
        self.assertEqual({p["kind"] for p in merged}, {"change", "ride"})


if __name__ == "__main__":
    unittest.main()
