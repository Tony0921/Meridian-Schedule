import csv
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path
from shutil import copytree
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from ingestion.schedule_csv import (COLUMNS, MAX_CSV_BYTES, PublicRedirect, download_csv,
                                    import_schedule, normalize_date, normalize_row, normalize_time, parse_csv)
from processor.schemas import ValidationError, load_json
from processor.storage import (NAMES, atomic_json, data_lock, load_snapshot, read_data,
                               recover_unlocked, snapshot)
from processor.validate import validate_data
from scripts.backup_data import main as backup_main
from scripts.import_schedule import main
from scripts.process_post import process_fixture

ROOT = Path(__file__).resolve().parents[1]
STAMP = "2026-10-28T08:00:00+08:00"


def row(**updates):
    return {"id": "demo-miri_20261028_01", "member_id": "demo-miri", "date": "2026-10-28",
            "time": "20:00", "title": "雜談直播", "source_url": "https://x.com/Demo/status/123456789",
            "created_at": "2026-10-28T02:10:00+08:00", **updates}


def csv_text(rows, columns=None):
    stream = io.StringIO(newline="")
    columns = columns or (*COLUMNS, *(key for key in ("platform", "group", "status", "event_status") if any(key in item for item in rows)))
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


class ScheduleCSVTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.backups = self.root / "backups"
        copytree(ROOT / "tests/fixtures/data", self.data)
        self.before = self.files()

    def files(self):
        return {path.name: path.read_bytes() for path in self.data.glob("*.json")}

    def run_import(self, rows, **kwargs):
        return import_schedule(csv_text(rows), self.data, self.backups, timestamp=STAMP, **kwargs)

    def test_import_records_schedule_sources_history_and_ids_without_api(self):
        result = self.run_import([row(), row(id="second", date="10/29", time="休息", title="休息日")])
        self.assertEqual(result["imported"], 2)
        self.assertTrue(result["schedule_changed"])
        values = read_data(self.data)
        events = [item for item in values["schedule"]["events"] if item["date"] >= "2026-10-28"]
        self.assertEqual([item["status"] for item in events], ["scheduled", "day_off"])
        self.assertEqual([item["id"] for item in events], [row()["id"], "second"])
        self.assertIsNone(events[1]["time"])
        self.assertEqual(len(values["posts"]), len(json.loads(self.before["posts.json"])) + 1)
        self.assertEqual(len(values["revisions"]), 2)
        self.assertEqual(load_json(self.data / "imported_ids.json"), [row()["id"], "second"])
        backup = load_snapshot(next(self.backups.glob("*.json")))
        self.assertEqual(backup["data"]["schedule"], json.loads(self.before["schedule.json"]))

    def test_repeat_does_not_change_bytes_timestamps_or_make_backup(self):
        self.run_import([row()])
        before = self.files()
        result = import_schedule(csv_text([row()]), self.data, self.backups, timestamp="2027-01-01T00:00:00Z")
        self.assertFalse(result["changed"])
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(self.files(), before)
        self.assertEqual(len(list(self.backups.glob("*.json"))), 1)

    def test_explicit_event_status_imports_all_six_states_without_changing_ids(self):
        states = (("scheduled", "20:00"), ("tbd", ""), ("day_off", ""), ("unknown", ""),
                  ("cancelled", "21:00"), ("postponed", ""))
        rows = [row(id=f"state-{state}", date=f"2026-11-{index + 1:02d}", time=time, event_status=state)
                for index, (state, time) in enumerate(states)]
        result = self.run_import(rows)
        self.assertEqual((result["imported"], result["invalid"]), (6, 0))
        values = read_data(self.data)
        events = {event["id"]: event for event in values["schedule"]["events"]}
        for state, time in states:
            with self.subTest(state=state):
                self.assertEqual((events[f"state-{state}"]["status"], events[f"state-{state}"]["time"]),
                                 (state, time or None))
        self.assertEqual(len(values["revisions"]), 6)

    def test_explicit_state_changes_keep_id_creation_time_and_revision(self):
        self.run_import([row(event_status="scheduled")])
        original = read_data(self.data)["schedule"]["events"][-1]
        for state, time in (("cancelled", "20:00"), ("postponed", ""), ("scheduled", "21:00"),
                            ("tbd", ""), ("day_off", ""), ("unknown", ""), ("scheduled", "22:00")):
            with self.subTest(state=state):
                self.assertTrue(self.run_import([row(event_status=state, time=time)])["schedule_changed"])
                values = read_data(self.data)
                event = values["schedule"]["events"][-1]
                self.assertEqual((event["id"], event["created_at"]), (original["id"], original["created_at"]))
                self.assertEqual((event["status"], event["time"]), (state, time or None))
                self.assertEqual(values["revisions"][-1]["after"], event)
        self.assertEqual(len(read_data(self.data)["revisions"]), 8)

    def test_explicit_content_correction_does_not_replace_event_state_with_changed(self):
        self.run_import([row(event_status="scheduled")])
        self.assertTrue(self.run_import([row(event_status="scheduled", title="修正標題")])["changed"])
        event = read_data(self.data)["schedule"]["events"][-1]
        self.assertEqual((event["status"], event["title"]), ("scheduled", "修正標題"))
        self.assertEqual(len(read_data(self.data)["revisions"]), 2)

    def test_legacy_to_explicit_conversion_is_a_noop_and_keeps_receipts(self):
        self.run_import([row(), row(id="unknown", date="2026-10-29", time="unknown"),
                         row(id="off", date="2026-10-30", time="day_off"),
                         row(id="tbd", date="2026-10-31", time="tbd")])
        before = self.files()
        result = self.run_import([row(event_status="scheduled"),
                                  row(id="unknown", date="2026-10-29", time="", event_status="unknown"),
                                  row(id="off", date="2026-10-30", time="", event_status="day_off"),
                                  row(id="tbd", date="2026-10-31", time="", event_status="tbd")])
        self.assertEqual((result["imported"], result["duplicates"], result["invalid"], result["changed"]), (0, 4, 0, False))
        self.assertEqual(self.files(), before)
        self.assertEqual(len(list(self.backups.glob("*.json"))), 1)

    def test_invalid_explicit_state_time_pairs_skip_only_bad_rows(self):
        invalids = (("", "20:00"), ("changed", "20:00"), ("live", "20:00"), ("finished", "20:00"),
                    ("scheduled", ""), ("unknown", "20:00"), ("day_off", "20:00"), ("tbd", "20:00"),
                    ("unknown", "unknown"), ("tbd", "tbd"), ("day_off", "休息"), ("cancelled", "unknown"),
                    ("postponed", "tbd"), ("scheduled", "25:00"))
        rows = [row(id=f"bad-{index}", time=time, event_status=state)
                for index, (state, time) in enumerate(invalids)]
        with self.assertLogs("ingestion.schedule_csv", level="WARNING"):
            result = self.run_import([*rows, row(event_status="scheduled")])
        self.assertEqual((result["imported"], result["invalid"]), (1, len(invalids)))
        self.assertEqual(load_json(self.data / "imported_ids.json"), [row()["id"]])

    def test_event_status_is_separate_from_optional_ingestion_status(self):
        with self.assertLogs("ingestion.schedule_csv", level="WARNING"):
            result = self.run_import([row(event_status="cancelled", status="imported"),
                                      row(id="disabled", event_status="scheduled", status="invalid")])
        self.assertEqual((result["imported"], result["invalid"]), (1, 1))
        self.assertEqual(read_data(self.data)["schedule"]["events"][-1]["status"], "cancelled")

    def test_explicit_state_normalization_retains_clock_format_compatibility(self):
        item = normalize_row(row(event_status=" SCHEDULED ", time="晚上八點"))
        self.assertEqual((item["time"], item["event_status"]), ("20:00", "scheduled"))
        legacy = normalize_row(row(time="待定"))
        self.assertEqual((legacy["time"], legacy["event_status"]), (None, "tbd"))

    def test_explicit_new_id_cannot_cancel_existing_event_implicitly(self):
        self.run_import([row(event_status="scheduled")])
        before = self.files()
        with self.assertLogs("ingestion.schedule_csv", level="WARNING"):
            result = self.run_import([row(id="new-cancel-id", event_status="cancelled")])
        self.assertEqual(result["invalid"], 1)
        self.assertEqual(self.files(), before)

    def test_optional_status_is_not_a_processing_receipt(self):
        with self.assertLogs("ingestion.schedule_csv", level="WARNING"):
            result = self.run_import([row(status="imported"), row(id="invalid", status="invalid", time="22:00")])
        self.assertEqual((result["imported"], result["invalid"]), (1, 1))
        self.assertEqual(load_json(self.data / "imported_ids.json"), [row()["id"]])

    def test_optional_group_is_informational_and_does_not_override_members(self):
        members = load_json(self.data / "members.json")
        result = self.run_import([row(group="neon"), row(group="aetris")])
        self.assertEqual((result["imported"], result["duplicates"], result["invalid"]), (1, 1, 0))
        values = read_data(self.data)
        self.assertEqual(values["members"], members)
        self.assertNotIn("group", values["schedule"]["events"][-1])
        before = self.files()
        self.assertFalse(self.run_import([row(group="collaborators")])["changed"])
        self.assertEqual(self.files(), before)

    def test_platform_is_normalized_and_saved_in_event_and_revision(self):
        for index, (value, expected) in enumerate(((" YouTube ", "youtube"), ("Twitch", "twitch"),
                                                  (" None ", "none"), ("UNKNOWN", "unknown"))):
            with self.subTest(platform=value):
                result = self.run_import([row(id=f"platform-{index}", time=f"{20 + index}:00", platform=value)])
                self.assertEqual(result["imported"], 1)
                values = read_data(self.data)
                event = values["schedule"]["events"][-1]
                self.assertEqual(event["platform"], expected)
                self.assertEqual(values["revisions"][-1]["after"], event)

    def test_rest_and_unknown_platform_remain_distinct(self):
        result = self.run_import([row(time="休息", platform="none"),
                                  row(id="unknown-platform", date="2026-10-29", platform="unknown")])
        self.assertEqual(result["imported"], 2)
        events = read_data(self.data)["schedule"]["events"][-2:]
        self.assertEqual([(event["status"], event["platform"]) for event in events],
                         [("day_off", "none"), ("scheduled", "unknown")])

    def test_other_platform_is_no_longer_accepted_from_csv(self):
        with self.assertLogs("ingestion.schedule_csv", level="WARNING"):
            result = self.run_import([row(platform="other")])
        self.assertEqual((result["imported"], result["invalid"]), (0, 1))
        self.assertEqual(self.files(), self.before)

    def test_missing_or_blank_platform_imports_as_unknown(self):
        for item in (row(), row(id="blank-platform", time="21:00", platform=" ")):
            self.assertEqual(self.run_import([item])["imported"], 1)
            self.assertIsNone(read_data(self.data)["schedule"]["events"][-1]["platform"])

    def test_invalid_platform_skips_only_the_bad_row(self):
        with self.assertLogs("ingestion.schedule_csv", level="WARNING"):
            result = self.run_import([row(platform="unknown-service"), row(id="valid", time="21:00", platform="twitch")])
        self.assertEqual((result["imported"], result["invalid"]), (1, 1))
        self.assertEqual(load_json(self.data / "imported_ids.json"), ["valid"])

    def test_platform_update_keeps_event_id_and_revision(self):
        self.run_import([row()])
        original = read_data(self.data)["schedule"]["events"][-1]
        self.assertTrue(self.run_import([row(platform="youtube")])["schedule_changed"])
        values = read_data(self.data)
        changed = values["schedule"]["events"][-1]
        self.assertEqual(changed["id"], original["id"])
        self.assertEqual((changed["platform"], changed["status"]), ("youtube", "changed"))
        self.assertEqual(values["revisions"][-1]["before"], original)
        self.assertEqual(values["revisions"][-1]["after"], changed)

    def test_imported_id_platform_update_is_saved_with_history_and_idempotent(self):
        self.run_import([row(platform="unknown")])
        original = read_data(self.data)
        before = original["schedule"]["events"][-1]
        receipt = (self.data / "imported_ids.json").read_bytes()
        updated_at = "2026-10-29T08:00:00+08:00"
        result = import_schedule(csv_text([row(platform="YouTube")]), self.data, self.backups,
                                 timestamp=updated_at)
        self.assertTrue(result["changed"])
        self.assertTrue(result["schedule_changed"])
        self.assertEqual((result["imported"], result["duplicates"], result["invalid"]), (1, 0, 0))
        values = read_data(self.data)
        after = values["schedule"]["events"][-1]
        self.assertEqual(after, {**before, "platform": "youtube", "status": "changed", "updated_at": updated_at})
        self.assertEqual(len(values["schedule"]["events"]), len(original["schedule"]["events"]))
        self.assertEqual(values["posts"], original["posts"])
        self.assertEqual(values["schedule"]["updated_at"], updated_at)
        self.assertEqual(len(values["revisions"]), 2)
        self.assertEqual(values["revisions"][-1]["before"], before)
        self.assertEqual(values["revisions"][-1]["after"], after)
        self.assertEqual((self.data / "imported_ids.json").read_bytes(), receipt)
        files = self.files()
        result = import_schedule(csv_text([row(platform="youtube")]), self.data, self.backups,
                                 timestamp="2026-10-30T08:00:00+08:00")
        self.assertFalse(result["changed"])
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(self.files(), files)
        self.assertEqual(len(list(self.backups.glob("*.json"))), 2)

    def test_imported_id_can_fill_missing_platform_and_change_known_platform(self):
        self.run_import([row()])
        for platform in ("youtube", "twitch", "none", "unknown"):
            with self.subTest(platform=platform):
                self.assertTrue(self.run_import([row(platform=platform)])["schedule_changed"])
                self.assertEqual(read_data(self.data)["schedule"]["events"][-1]["platform"], platform)
        self.assertEqual(len(read_data(self.data)["revisions"]), 5)

    def test_imported_id_platform_update_preserves_terminal_states(self):
        self.run_import([row(platform="unknown")])
        for status in ("cancelled", "postponed", "live", "finished"):
            with self.subTest(status=status):
                values = read_data(self.data)
                before = values["schedule"]["events"][-1]
                before.update(status=status, platform="unknown")
                atomic_json(values["schedule"], self.data / "schedule.json")
                result = self.run_import([row(platform="twitch")])
                self.assertTrue(result["schedule_changed"])
                after = read_data(self.data)["schedule"]["events"][-1]
                self.assertEqual(after, {**before, "platform": "twitch", "updated_at": STAMP})

    def test_imported_id_platform_update_preserves_source_metadata(self):
        self.run_import([row(platform="unknown")])
        posts = load_json(self.data / "posts.json")
        posts.insert(0, {**posts[-1], "post_id": "same-url-alias"})
        atomic_json(posts, self.data / "posts.json")
        for confidence in (0.98, 0.40):
            with self.subTest(confidence=confidence):
                values = read_data(self.data)
                before = values["schedule"]["events"][-1]
                before.update(platform="unknown", confidence=confidence)
                atomic_json(values["schedule"], self.data / "schedule.json")
                self.assertTrue(self.run_import([row(platform="twitch")])["schedule_changed"])
                values = read_data(self.data)
                after = values["schedule"]["events"][-1]
                self.assertEqual(after, {**before, "platform": "twitch", "status": "changed", "updated_at": STAMP})
                self.assertEqual(values["revisions"][-1]["before"], before)
                self.assertEqual(values["revisions"][-1]["after"], after)
                self.assertEqual(values["revisions"][-1]["source_post_id"], before["source_post_id"])
                self.assertEqual(values["posts"], posts)

    def test_same_id_uses_identity_even_when_multiple_events_share_time(self):
        self.run_import([row(platform="unknown")])
        values = read_data(self.data)
        other = {**values["schedule"]["events"][-1], "id": "other-event", "title": "遊戲直播"}
        values["schedule"]["events"].append(other)
        atomic_json(values["schedule"], self.data / "schedule.json")
        self.assertTrue(self.run_import([row(platform="youtube")])["schedule_changed"])
        events = {event["id"]: event for event in read_data(self.data)["schedule"]["events"]}
        self.assertEqual(events[row()["id"]]["platform"], "youtube")
        self.assertEqual(events["other-event"], other)

    def test_receipt_does_not_prevent_inserting_absent_event(self):
        atomic_json([row()["id"]], self.data / "imported_ids.json")
        self.assertTrue(self.run_import([row()])["schedule_changed"])
        self.assertEqual(read_data(self.data)["schedule"]["events"][-1]["id"], row()["id"])

    def test_imported_id_platform_noops_do_not_clear_or_rewrite_data(self):
        self.run_import([row(platform="twitch")])
        before = self.files()
        for item in (row(), row(platform=""), row(platform="TWITCH"), row(created_at="2027-01-01T00:00:00Z")):
            with self.subTest(item=item):
                result = self.run_import([item])
                self.assertFalse(result["changed"])
                self.assertEqual(result["duplicates"], 1)
                self.assertEqual(self.files(), before)
        self.assertEqual(len(list(self.backups.glob("*.json"))), 1)

    def test_imported_id_conflicting_or_invalid_platforms_leave_data_unchanged(self):
        self.run_import([row(platform="unknown")])
        before = self.files()
        for items, invalid in (([row(platform="youtube"), row(platform="twitch")], 2),
                               ([row(platform="other")], 1),
                               ([row(platform="youtube", status="invalid")], 1)):
            with self.subTest(items=items), self.assertLogs("ingestion.schedule_csv", level="WARNING"):
                result = self.run_import(items)
            self.assertEqual(result["invalid"], invalid)
            self.assertEqual(self.files(), before)

    def test_imported_id_platform_write_failure_rolls_back_without_new_receipt(self):
        self.run_import([row(platform="unknown")])
        before = self.files()
        real = atomic_json

        def fail_history(value, path):
            if Path(path).name == "revisions.json":
                raise OSError("simulated full disk")
            real(value, path)

        with patch("processor.storage.atomic_json", side_effect=fail_history), self.assertRaises(OSError):
            self.run_import([row(platform="youtube")])
        self.assertEqual(self.files(), before)
        self.assertFalse((self.data / ".transaction.json").exists())

    def test_missing_or_blank_platform_preserves_known_platform(self):
        self.run_import([row(platform="twitch")])
        for item in (row(), row(platform="")):
            self.assertFalse(self.run_import([item])["schedule_changed"])
            self.assertEqual(read_data(self.data)["schedule"]["events"][-1]["platform"], "twitch")
        self.assertEqual(len(read_data(self.data)["revisions"]), 1)

    def test_conflicting_platforms_with_same_row_id_are_skipped(self):
        with self.assertLogs("ingestion.schedule_csv", level="WARNING"):
            result = self.run_import([row(platform="youtube"), row(platform="twitch")])
        self.assertEqual((result["imported"], result["invalid"]), (0, 2))
        self.assertEqual(self.files(), self.before)

    def test_invalid_rows_warn_and_allow_valid_rows_and_later_correction(self):
        invalids = [{"id": ""}, {"member_id": "missing"}, {"date": "2026-02-30"}, {"time": "25:00"},
                    {"title": " "}, {"source_url": "javascript:alert(1)"}, {"created_at": "2026-10-28"},
                    {"source_url": "https://user:private-value@example.com/a"}, {"time": ""}, {"status": "review"},
                    {"created_at": "9999-12-31T23:00:00Z"}]
        rows = [row(**{**values, "id": values.get("id", f"bad-{index}")}) for index, values in enumerate(invalids)]
        with self.assertLogs("ingestion.schedule_csv", level="WARNING") as logs:
            result = self.run_import([*rows, row()])
        self.assertEqual((result["imported"], result["invalid"]), (1, len(invalids)))
        self.assertNotIn("private-value", " ".join(logs.output))
        self.assertEqual(self.run_import([row(id="bad-3", time="21:00")])["imported"], 1)

    def test_disabled_member_is_skipped(self):
        members = load_json(self.data / "members.json")
        members[0]["enabled"] = False
        atomic_json(members, self.data / "members.json")
        with self.assertLogs("ingestion.schedule_csv", level="WARNING"):
            self.assertEqual(self.run_import([row()])["invalid"], 1)
        self.assertFalse((self.data / "imported_ids.json").exists())

    def test_schema_or_late_csv_syntax_failure_preserves_all_files(self):
        for text in ("", "<html>sign in</html>", "id,title\na,b\n", ",".join((*COLUMNS, "id")),
                     csv_text([row()]) + '"unclosed', csv_text([], columns=(*COLUMNS, "operation"))):
            with self.subTest(text=text[:30]), self.assertRaises(ValidationError):
                import_schedule(text, self.data, self.backups, timestamp=STAMP)
            self.assertEqual(self.files(), self.before)
        self.assertFalse(self.backups.exists())

    def test_header_only_and_all_invalid_are_noops(self):
        self.assertFalse(self.run_import([])["changed"])
        with self.assertLogs("ingestion.schedule_csv", level="WARNING"):
            self.assertFalse(self.run_import([row(time="?")])["changed"])
        self.assertEqual(self.files(), self.before)

    def test_bom_reordered_headers_quoted_multiline_and_ragged_row(self):
        text = "\ufeff" + csv_text([row(title='雜談, "直播"\n第二行')], columns=tuple(reversed(COLUMNS)))
        text += "not,enough,columns\r\n"
        with self.assertLogs("ingestion.schedule_csv", level="WARNING"):
            result = import_schedule(text, self.data, self.backups, timestamp=STAMP)
        self.assertEqual((result["imported"], result["invalid"]), (1, 1))
        self.assertEqual(read_data(self.data)["schedule"]["events"][-1]["title"], '雜談, "直播"\n第二行')

    def test_duplicate_ids_and_natural_keys_do_not_duplicate_events(self):
        result = self.run_import([row(), row(), row(id="another-id")])
        self.assertEqual((result["imported"], result["duplicates"]), (1, 2))
        values = read_data(self.data)
        self.assertEqual(len(values["revisions"]), 1)
        self.assertEqual(load_json(self.data / "imported_ids.json"), [row()["id"]])

    def test_conflicting_duplicate_id_skips_all_versions(self):
        with self.assertLogs("ingestion.schedule_csv", level="WARNING"):
            result = self.run_import([row(), row(title="另一個標題")])
        self.assertEqual(result["imported"], 0)
        self.assertFalse(result["changed"])
        self.assertEqual(self.files(), self.before)

    def test_title_update_uses_existing_id_and_keeps_revision(self):
        self.run_import([row()])
        original = read_data(self.data)["schedule"]["events"][-1]
        self.run_import([row(title="改標題", source_url="https://discord.com/channels/1/2/3")])
        values = read_data(self.data)
        changed = values["schedule"]["events"][-1]
        self.assertEqual(changed["id"], original["id"])
        self.assertEqual((changed["title"], changed["status"]), ("改標題", "changed"))
        self.assertEqual(values["revisions"][-1]["before"], original)
        self.assertEqual(values["posts"][-1]["source"], "discord")

    def test_new_id_similar_event_warns_without_overwriting_or_receipt(self):
        self.run_import([row(platform="youtube")])
        before = self.files()
        for updates in ({"title": "雜談直播！"}, {"platform": "twitch"}):
            with self.subTest(updates=updates), self.assertLogs("ingestion.schedule_csv", level="WARNING"):
                result = self.run_import([row(**{"id": "new-id", "platform": "youtube", **updates})])
            self.assertEqual((result["imported"], result["invalid"]), (0, 1))
            self.assertEqual(self.files(), before)
        self.assertEqual(len(list(self.backups.glob("*.json"))), 1)

    def test_changed_imported_id_updates_time_and_retains_identity(self):
        self.run_import([row()])
        before = read_data(self.data)["schedule"]["events"][-1]
        self.assertTrue(self.run_import([row(time="21:00")])["schedule_changed"])
        values = read_data(self.data)
        self.assertEqual(values["schedule"]["events"][-1]["id"], row()["id"])
        self.assertEqual(values["schedule"]["events"][-1]["time"], "21:00")
        self.assertEqual(values["revisions"][-1]["before"], before)

    def test_same_id_updates_all_mutable_fields_and_preserves_creation_time(self):
        self.run_import([row(platform="youtube")])
        before = read_data(self.data)["schedule"]["events"][-1]
        changed = row(date="2026-11-02", time="21:30", title="修正版遊戲直播", platform="twitch",
                      source_url="https://discord.com/channels/1/2/3", created_at="2026-10-30T12:00:00Z")
        result = self.run_import([changed])
        self.assertEqual((result["imported"], result["invalid"]), (1, 0))
        values = read_data(self.data)
        event = values["schedule"]["events"][-1]
        self.assertEqual((event["id"], event["date"], event["time"], event["title"], event["platform"]),
                         (row()["id"], "2026-11-02", "21:30", "修正版遊戲直播", "twitch"))
        self.assertEqual(event["created_at"], "2026-10-28T02:10:00+08:00")
        self.assertEqual(values["revisions"][-1]["before"], before)
        self.assertEqual(values["revisions"][-1]["after"], event)
        files = self.files()
        self.assertFalse(self.run_import([changed])["changed"])
        self.assertEqual(self.files(), files)

    def test_source_only_update_keeps_old_source_and_revision_urls(self):
        self.run_import([row()])
        original = read_data(self.data)
        result = self.run_import([row(source_url="https://example.com/revised")])
        self.assertTrue(result["schedule_changed"])
        values = read_data(self.data)
        revision = values["revisions"][-1]
        self.assertEqual(revision["before"]["source_url"], "https://x.com/Demo/status/123456789")
        self.assertEqual(revision["after"]["source_url"], "https://example.com/revised")
        self.assertEqual(values["posts"][:-1], original["posts"])
        self.assertEqual(revision["source_post_id"], values["posts"][-1]["post_id"])

    def test_legacy_proposal_keeps_csv_event_source_url_and_history_consistent(self):
        self.run_import([row()])
        fixture = load_json(ROOT / "tests/fixtures/schedule-change.json")
        fixture["proposal"]["changes"][0]["match"] = {"id": row()["id"], "member_id": "demo-miri"}
        candidate = process_fixture(fixture, self.data, STAMP)
        for name in NAMES:
            atomic_json(candidate[name], self.data / f"{name}.json")
        values = read_data(self.data)
        event = values["schedule"]["events"][-1]
        self.assertEqual(event["source_url"], "https://example.com/fixtures/change")
        self.assertEqual(event["created_at"], "2026-10-28T02:10:00+08:00")
        self.assertEqual(values["revisions"][-1]["after"]["source_url"], "https://example.com/fixtures/change")
        files = self.files()
        self.assertFalse(self.run_import([row(time="21:00", source_url="https://example.com/fixtures/change")])["changed"])
        self.assertEqual(self.files(), files)

    def test_short_date_uses_immutable_creation_time_on_update(self):
        self.run_import([row(date="10/28")])
        before = self.files()
        result = self.run_import([row(date="10/28", created_at="2027-10-28T00:00:00Z")])
        self.assertFalse(result["changed"])
        self.assertEqual(self.files(), before)
        self.assertTrue(self.run_import([row(date="10/29", created_at="2027-10-28T00:00:00Z")])["changed"])
        self.assertEqual(read_data(self.data)["schedule"]["events"][-1]["date"], "2026-10-29")

    def test_special_states_can_be_corrected_to_confirmed_times_with_same_id(self):
        for state, day in (("tbd", "2026-11-01"), ("unknown", "2026-11-02"), ("day_off", "2026-11-03")):
            with self.subTest(state=state):
                identity = f"state-{state}"
                self.run_import([row(id=identity, date=day, time=state)])
                result = self.run_import([row(id=identity, date=day, time="22:00")])
                self.assertTrue(result["schedule_changed"])
                event = next(event for event in read_data(self.data)["schedule"]["events"] if event["id"] == identity)
                self.assertEqual((event["time"], event["status"]), ("22:00", "changed"))
        self.assertEqual(len(read_data(self.data)["revisions"]), 6)

    def test_same_id_member_change_is_rejected_and_valid_rows_continue(self):
        self.run_import([row()])
        before = read_data(self.data)["schedule"]["events"][-1]
        with self.assertLogs("ingestion.schedule_csv", level="WARNING"):
            result = self.run_import([row(member_id="demo-snow"), row(id="valid-next", date="2026-10-29")])
        self.assertEqual((result["imported"], result["invalid"]), (1, 1))
        event = next(event for event in read_data(self.data)["schedule"]["events"] if event["id"] == row()["id"])
        self.assertEqual(event, before)

    def test_date_or_time_update_collision_does_not_change_files(self):
        self.run_import([row(), row(id="other", date="2026-10-29")])
        before = self.files()
        with self.assertLogs("ingestion.schedule_csv", level="WARNING"):
            result = self.run_import([row(date="2026-10-29")])
        self.assertEqual(result["invalid"], 1)
        self.assertEqual(self.files(), before)

    def test_existing_schedule_id_updates_without_receipt_and_keeps_legacy_metadata(self):
        event = load_json(self.data / "schedule.json")["events"][0]
        self.assertTrue(self.run_import([row(id=event["id"], date=event["date"], time="21:00")])["schedule_changed"])
        values = read_data(self.data)
        changed = next(item for item in values["schedule"]["events"] if item["id"] == event["id"])
        self.assertEqual((changed["time"], changed["confidence"], changed["origin"]),
                         ("21:00", 0.98, "weekly_schedule"))
        self.assertEqual(len(values["schedule"]["events"]), 5)
        self.assertEqual(values["revisions"][-1]["before"]["source_url"], "https://example.com/demo/weekly-001")

    def test_new_id_exact_duplicate_with_different_source_does_not_write(self):
        self.run_import([row(platform="youtube")])
        before = self.files()
        result = self.run_import([row(id="alias", platform="youtube", source_url="https://example.com/other")])
        self.assertEqual((result["duplicates"], result["invalid"]), (1, 0))
        self.assertFalse(result["changed"])
        self.assertEqual(self.files(), before)
        self.assertEqual(len(list(self.backups.glob("*.json"))), 1)

    def test_distinct_event_same_slot_is_inserted_without_merging(self):
        self.run_import([row()])
        result = self.run_import([row(id="different", title="Minecraft 建築夜")])
        self.assertEqual(result["imported"], 1)
        events = read_data(self.data)["schedule"]["events"]
        self.assertEqual(len(events), 7)
        self.assertEqual({event["title"] for event in events if event["date"] == "2026-10-28"},
                         {"雜談直播", "Minecraft 建築夜"})

    def test_removed_csv_rows_do_not_delete_events(self):
        self.run_import([row(), row(id="other", date="2026-10-29")])
        before = self.files()
        self.assertFalse(self.run_import([row()])["changed"])
        self.assertEqual(self.files(), before)

    def test_status_and_group_changes_do_not_create_conflicts(self):
        result = self.run_import([row(group="neon", status="pending"), row(group="none", status="imported")])
        self.assertEqual((result["imported"], result["duplicates"], result["invalid"]), (1, 1, 0))

    def test_known_source_still_imports_additional_rows(self):
        self.run_import([row()])
        result = self.run_import([row(id="second", date="2026-10-29")])
        self.assertEqual(result["imported"], 1)
        values = read_data(self.data)
        self.assertEqual(len(values["posts"]), len(json.loads(self.before["posts.json"])) + 1)
        self.assertEqual(len(values["revisions"]), 2)

    def test_twitter_tracking_alias_reuses_source(self):
        self.run_import([row()])
        self.run_import([row(id="second", date="2026-10-29", source_url="https://twitter.com/Demo/status/123456789?s=20")])
        self.assertEqual(len(read_data(self.data)["posts"]), len(json.loads(self.before["posts.json"])) + 1)

    def test_generic_public_source_and_special_times_are_valid_for_site(self):
        self.run_import([row(source_url="https://example.com/public", time="TBD"),
                         row(id="unknown", source_url="https://example.com/public", date="2026/10/29", time="unknown")])
        values = read_data(self.data)
        self.assertEqual(values["posts"][-1]["source"], "other")
        self.assertEqual([event["status"] for event in values["schedule"]["events"][-2:]], ["tbd", "unknown"])
        self.assertIsNone(values["schedule"]["events"][-1]["time"])
        self.assertEqual(values["revisions"][-1]["after"]["status"], "unknown")
        self.assertFalse(self.run_import([row(id="unknown", source_url="https://example.com/public",
                                             date="2026/10/29", time="unknown")])["changed"])

    def test_missing_or_ambiguous_non_x_source_is_rejected(self):
        self.run_import([row(source_url="https://discord.com/channels/1/2/3")])
        values = read_data(self.data)
        values["posts"].append({**values["posts"][-1], "source": "other"})
        with self.assertRaisesRegex(ValidationError, "不唯一"):
            validate_data(*(values[name] for name in NAMES))
        values["posts"] = values["posts"][:-2]
        with self.assertRaises(ValidationError):
            validate_data(*(values[name] for name in NAMES))

    def test_receipt_write_failure_rolls_back_all_data_and_receipts(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                if existing:
                    self.run_import([row()])
                before = self.files()
                real = atomic_json
                def fail_ids(value, path):
                    if Path(path).name == "imported_ids.json":
                        raise OSError("simulated full disk")
                    real(value, path)
                with patch("processor.storage.atomic_json", side_effect=fail_ids), self.assertRaises(OSError):
                    self.run_import([row(id="new", date="2026-10-29")])
                self.assertEqual(self.files(), before)
                self.assertFalse((self.data / ".transaction.json").exists())

    def test_interrupted_transaction_recovers_receipts_and_old_backup_clears_them(self):
        self.run_import([row()])
        before = self.files()
        with data_lock(self.data):
            backup = snapshot(self.data, self.backups)
        atomic_json(load_json(backup), self.data / ".transaction.json")
        atomic_json(["incorrect"], self.data / "imported_ids.json")
        with self.assertRaises(ValidationError):
            self.run_import([row()])
        with data_lock(self.data):
            self.assertTrue(recover_unlocked(self.data))
        self.assertEqual(self.files(), before)
        old_backup = next(path for path in self.backups.glob("*.json") if "imported_ids" not in load_snapshot(path)["data"])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(backup_main(["restore", "--snapshot", str(old_backup), "--data-dir", str(self.data),
                                          "--backup-dir", str(self.backups)]), 0)
        self.assertEqual(load_json(self.data / "imported_ids.json"), [])
        self.assertEqual(read_data(self.data)["schedule"], json.loads(self.before["schedule.json"]))

    def test_invalid_receipt_or_concurrent_writer_blocks_import(self):
        atomic_json({}, self.data / "imported_ids.json")
        with self.assertRaises(ValidationError):
            self.run_import([row()])
        atomic_json([], self.data / "imported_ids.json")
        with data_lock(self.data), self.assertRaises(ValidationError):
            self.run_import([row()])

    def test_cli_local_url_and_download_failure_preserve_previous_data(self):
        path = self.root / "schedule.csv"
        path.write_text(csv_text([row()]), encoding="utf-8-sig")
        args = ["--data-dir", str(self.data), "--backup-dir", str(self.backups)]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--input", str(path), *args]), 0)
        before = self.files()
        with patch.dict(os.environ, {"SCHEDULE_CSV_URL": "https://example.com/public.csv"}), \
                patch("scripts.import_schedule.download_csv", return_value=csv_text([row()])) as download, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 0)
            download.assert_called_once_with("https://example.com/public.csv")
        with patch("scripts.import_schedule.download_csv", side_effect=ValidationError("download failed")), redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--url", "https://example.com/public.csv", *args]), 1)
        self.assertEqual(self.files(), before)


class CSVNormalizationTests(unittest.TestCase):
    def test_time_formats_and_explicit_special_values(self):
        for value in ("20：00", "20:00", "8:00 PM", "晚上八點", "晚間八時"):
            self.assertEqual(normalize_time(value), "20:00")
        for value, expected in (("12 AM", "00:00"), ("12 PM", "12:00"), ("上午十二點", "00:00"),
                                ("下午三點半", "15:30"), ("凌晨一點五分", "01:05"), ("晚上十二點", "00:00"),
                                ("TBD", "tbd"), ("休息日", "day_off"),
                                ("unknown", "unknown"), (" UNKNOWN ", "unknown"), ("未知", "unknown")):
            self.assertEqual(normalize_time(value), expected)
        for value in ("24:00", "8:60 PM", "0 PM", "25 PM", "", "?", "下班後",
                      "working_day", "工作日", "作業日"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                normalize_time(value)

    def test_dates_use_creation_date_for_year_and_taiwan_timezone(self):
        from datetime import date
        reference = date(2026, 10, 28)
        for value in ("10/28", "2026/10/28", "Oct 28", "October 28, 2026", "2026-10-28"):
            self.assertEqual(normalize_date(value, reference), "2026-10-28")
        self.assertEqual(normalize_date("1/1", date(2026, 12, 31)), "2027-01-01")
        self.assertEqual(normalize_date("12/31", date(2027, 1, 1)), "2026-12-31")
        self.assertEqual(normalize_date("2/29", date(2025, 1, 1)), "2024-02-29")
        with self.assertRaises(ValueError):
            normalize_date("2026/2/29", reference)
        self.assertEqual(parse_csv(csv_text([row()]))[0][1]["date"], "2026-10-28")

    def test_public_download_is_bounded_utf8_get_without_authorization(self):
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        response.read.return_value = ("\ufeff" + csv_text([row()])).encode()
        with patch("ingestion.schedule_csv.build_opener", return_value=opener):
            self.assertTrue(download_csv("https://example.com/public.csv").startswith("id,"))
            request = opener.open.call_args.args[0]
            self.assertEqual(request.get_method(), "GET")
            self.assertFalse(request.has_header("Authorization"))
            response.read.assert_called_once_with(MAX_CSV_BYTES + 1)
            response.read.return_value = b"x" * (MAX_CSV_BYTES + 1)
            with self.assertRaises(ValidationError):
                download_csv("https://example.com/public.csv")

    def test_download_errors_and_unsafe_urls_do_not_echo_response_or_credentials(self):
        for error in (URLError("private response"), HTTPError("https://example.com", 403, "private response", {}, None)):
            opener = MagicMock()
            opener.open.side_effect = error
            with patch("ingestion.schedule_csv.build_opener", return_value=opener), self.assertRaises(ValidationError) as caught:
                download_csv("https://example.com/public.csv")
            self.assertNotIn("private response", str(caught.exception))
        for url in ("http://example.com/public.csv", "https://user:private-value@example.com/public.csv"):
            with self.assertRaises(ValidationError):
                download_csv(url)
        with self.assertRaises(ValidationError):
            PublicRedirect().redirect_request(None, None, 302, "", {}, "http://example.com/public.csv")
