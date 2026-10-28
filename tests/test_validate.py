import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from processor.schemas import ValidationError, load_json, validate_schema
from processor.validate import validate_data, validate_members, validate_schedule
from scripts.build_site import build_site

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests/fixtures/data"


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.members, self.schedule, self.posts, self.revisions = [
            load_json(DATA / f"{name}.json") for name in ("members", "schedule", "posts", "revisions")]

    def test_demo_data_valid(self):
        validate_data(self.members, self.schedule, self.posts, self.revisions)

    def test_member_groups_are_preserved(self):
        self.members[0].update(group="neon", group_name="霓 NEO(n)")
        self.members[1].update(group="other", group_name="其他")
        members = validate_members(self.members)
        self.assertEqual([(member.group, member.group_name) for member in members],
                         [("neon", "霓 NEO(n)"), ("other", "其他")])

    def test_member_group_fields_are_required_and_valid(self):
        for member in self.members:
            member.update(group="other", group_name="其他")
        for key in ("group", "group_name"):
            candidate = deepcopy(self.members)
            del candidate[0][key]
            with self.subTest(missing=key), self.assertRaisesRegex(ValidationError, key):
                validate_members(candidate)
        for key, value in (("group", ""), ("group", None), ("group", "NEO(n)"),
                           ("group_name", ""), ("group_name", None)):
            candidate = deepcopy(self.members)
            candidate[0][key] = value
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ValidationError, key):
                validate_members(candidate)

    def test_invalid_event_fields(self):
        invalids = {"date": "2026-02-30", "time": "24:00", "timezone": "UTC", "status": "sudden",
                    "confidence": 1.1, "url": "javascript:alert(1)", "updated_at": "2026-10-16T12:00:00"}
        for key, value in invalids.items():
            candidate = deepcopy(self.schedule)
            candidate["events"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValidationError):
                validate_schedule(candidate, self.members)

    def test_non_finite_and_boolean_confidence_rejected(self):
        for value in (float("nan"), float("inf"), True):
            self.schedule["events"][0]["confidence"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_schedule(self.schedule, self.members)

    def test_date_time_requires_rfc3339_shape(self):
        for value in ("20261016T180000+0800", "2026-10-16T18:00+08:00"):
            self.schedule["events"][0]["updated_at"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_schedule(self.schedule, self.members)

    def test_duplicate_and_unknown_ids_rejected(self):
        self.schedule["events"].append(deepcopy(self.schedule["events"][0]))
        with self.assertRaises(ValidationError):
            validate_schedule(self.schedule, self.members)
        self.schedule["events"].pop()
        self.schedule["events"][0]["member_id"] = "missing"
        with self.assertRaises(ValidationError):
            validate_schedule(self.schedule, self.members)

    def test_null_time_requires_appropriate_status(self):
        self.schedule["events"][0]["time"] = None
        with self.assertRaises(ValidationError):
            validate_schedule(self.schedule, self.members)
        self.schedule["events"][0]["status"] = "tbd"
        validate_schedule(self.schedule, self.members)

    def test_empty_schedule_allowed(self):
        validate_schedule({"updated_at": None, "events": []}, self.members)

    def test_missing_post_rejected(self):
        with self.assertRaises(ValidationError):
            validate_data(self.members, self.schedule, [], [])

    def test_source_cannot_belong_to_another_member(self):
        self.schedule["events"][0]["source_post_id"] = "demo-weekly-002"
        with self.assertRaisesRegex(ValidationError, "其他成員"):
            validate_data(self.members, self.schedule, self.posts, self.revisions)

    def test_revision_snapshots_are_validated(self):
        event = deepcopy(self.schedule["events"][0])
        self.revisions.append({"event_id": event["id"], "timestamp": event["updated_at"],
                               "source_post_id": event["source_post_id"], "before": None, "after": event})
        validate_data(self.members, self.schedule, self.posts, self.revisions)
        event["time"] = "99:00"
        with self.assertRaises(ValidationError):
            validate_data(self.members, self.schedule, self.posts, self.revisions)

    def test_unknown_schema_fields_rejected(self):
        self.members[0]["secret"] = "not-allowed"
        with self.assertRaises(ValidationError):
            validate_schema(self.members, "members")

    def test_build_contains_only_public_data(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "public"
            build_site(output)
            self.assertEqual({path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()},
                             {"index.html", "app.js", "style.css", ".nojekyll", "data/members.json", "data/schedule.json"})
            self.assertEqual(load_json(output / "data/members.json"), load_json(ROOT / "data/members.json"))
            published = load_json(output / "data/schedule.json")
            sources = {post["post_id"]: post["source_url"] for post in load_json(ROOT / "data/posts.json")}
            self.assertEqual(published["sources"], {event["source_post_id"]: sources[event["source_post_id"]]
                                                    for event in published["events"]})

    def test_build_cannot_overwrite_source(self):
        for directory in (ROOT, ROOT / "site", ROOT / "data/nested"):
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                build_site(directory)


if __name__ == "__main__":
    unittest.main()
