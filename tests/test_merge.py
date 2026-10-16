import unittest
from copy import deepcopy
from pathlib import Path

from processor.classify import ConfidencePolicy
from processor.merge import merge_changes
from processor.schemas import ValidationError, load_json
from scripts.process_post import process_fixture

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests/fixtures/data"
STAMP = "2026-10-16T18:30:00+08:00"


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.members = load_json(DATA / "members.json")
        self.schedule = load_json(DATA / "schedule.json")

    def fixture(self, name):
        return load_json(ROOT / "tests/fixtures" / f"{name}.json")

    def merge(self, fixture, schedule=None, **kwargs):
        return merge_changes(self.schedule if schedule is None else schedule, fixture["proposal"], self.members,
                             source_post_id=fixture["post"]["post_id"], member_id=fixture["post"]["member_id"],
                             timestamp=STAMP, **kwargs)

    def test_weekly_inserts_with_provenance_and_revision(self):
        result = self.merge(self.fixture("weekly"))
        self.assertEqual(len(result.schedule["events"]), len(self.schedule["events"]) + 2)
        self.assertEqual(result.decision, "review")
        self.assertEqual(len(result.revisions), 2)
        self.assertIsNone(result.revisions[0]["before"])
        self.assertEqual(result.revisions[0]["after"]["source_post_id"], "fixture-weekly")

    def test_time_change_preserves_original_and_history(self):
        before = deepcopy(self.schedule)
        result = self.merge(self.fixture("schedule-change"))
        self.assertEqual(self.schedule, before)
        revision = result.revisions[0]
        self.assertEqual(revision["before"]["time"], "20:00")
        self.assertEqual(revision["after"]["time"], "21:00")
        self.assertEqual(revision["after"]["status"], "changed")

    def test_cancel_keeps_event(self):
        result = self.merge(self.fixture("cancellation"))
        self.assertEqual(len(result.schedule["events"]), len(self.schedule["events"]))
        self.assertEqual(result.revisions[0]["after"]["status"], "cancelled")

    def test_sudden_origin(self):
        result = self.merge(self.fixture("sudden-stream"))
        self.assertEqual(result.revisions[0]["after"]["origin"], "sudden_stream")

    def test_irrelevant_ignored(self):
        result = self.merge(self.fixture("irrelevant"))
        self.assertEqual(result.schedule, self.schedule)
        self.assertEqual(result.revisions, [])
        self.assertEqual(result.decision, "ignored")

    def test_uncertain_never_changes_schedule(self):
        result = self.merge(self.fixture("uncertain"))
        self.assertEqual(result.decision, "record_only")
        self.assertEqual(result.schedule, self.schedule)
        self.assertEqual(result.revisions, [])

    def test_configurable_confidence_boundaries(self):
        policy = ConfidencePolicy(review_all=False)
        self.assertEqual(policy.decide(0.699), "record_only")
        self.assertEqual(policy.decide(0.70), "review")
        self.assertEqual(policy.decide(0.949), "review")
        self.assertEqual(policy.decide(0.95), "auto")
        with self.assertRaises(ValueError):
            ConfidencePolicy(auto_threshold=0.5)

    def test_repeat_insert_is_idempotent(self):
        fixture = self.fixture("weekly")
        first = self.merge(fixture)
        second = self.merge(fixture, first.schedule)
        self.assertEqual(second.schedule, first.schedule)
        self.assertEqual(second.revisions, [])

    def test_repeat_update_is_idempotent(self):
        fixture = self.fixture("schedule-change")
        first = self.merge(fixture)
        second = self.merge(fixture, first.schedule)
        self.assertEqual(second.schedule, first.schedule)
        self.assertEqual(second.revisions, [])

    def test_batch_failure_does_not_mutate_input(self):
        fixture = self.fixture("schedule-change")
        fixture["proposal"]["changes"].append({"operation": "cancel", "match": {"member_id": "demo-miri", "date": "2099-01-01"}})
        before = deepcopy(self.schedule)
        with self.assertRaises(ValidationError):
            self.merge(fixture)
        self.assertEqual(self.schedule, before)

    def test_ambiguous_match_rejected(self):
        duplicate = deepcopy(self.schedule["events"][0])
        duplicate.update(id="another-event", title="另一場直播", time="22:00")
        self.schedule["events"].append(duplicate)
        with self.assertRaisesRegex(ValidationError, "不明確"):
            self.merge(self.fixture("cancellation"))

    def test_title_and_time_disambiguate(self):
        duplicate = deepcopy(self.schedule["events"][0])
        duplicate.update(id="another-event", title="另一場直播", time="22:00")
        self.schedule["events"].append(duplicate)
        fixture = self.fixture("schedule-change")
        fixture["proposal"]["changes"][0]["match"].update(title="Minecraft 建築夜", time="20:00", platform="youtube")
        self.assertEqual(self.merge(fixture).revisions[0]["event_id"], self.schedule["events"][0]["id"])

    def test_cross_member_and_metadata_edits_rejected(self):
        for fields in ({"member_id": "demo-snow"}, {"id": "override"}, {"source_post_id": "fake"}):
            fixture = self.fixture("schedule-change")
            fixture["proposal"]["changes"][0]["set"].update(fields)
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                self.merge(fixture)

    def test_bad_time_rejected(self):
        fixture = self.fixture("schedule-change")
        fixture["proposal"]["changes"][0]["set"]["time"] = "25:00"
        with self.assertRaises(ValidationError):
            self.merge(fixture)

    def test_all_six_fixtures_produce_valid_bundles(self):
        for path in (ROOT / "tests/fixtures").glob("*.json"):
            with self.subTest(path=path.name):
                result = process_fixture(load_json(path), DATA, STAMP)
                self.assertIn(result["decision"], {"review", "record_only", "ignored"})


if __name__ == "__main__":
    unittest.main()
