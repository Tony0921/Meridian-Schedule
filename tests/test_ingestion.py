import io
import json
import os
import tempfile
import unittest
from copy import deepcopy
from contextlib import redirect_stdout
from pathlib import Path
from shutil import copytree
from unittest.mock import Mock, MagicMock, patch
from uuid import uuid4

from collector.http import ServiceError
from ingestion.dedupe import IngestionStore
from ingestion.google_sheets import GoogleSheetsObservationSource, JsonObservationSource, access_token, table_rows
from ingestion.importer import import_queue
from ingestion.models import POST_COLUMNS, CHANGE_COLUMNS
from ingestion.normalize import normalize, to_fixture
from processor.classify import ConfidencePolicy
from processor.schemas import ValidationError, load_json
from processor.storage import atomic_json, data_lock, read_data
from scripts.apply_proposal import apply_proposal
from scripts.health_check import main as health_main
from scripts.import_sheet import main as import_main

ROOT = Path(__file__).resolve().parents[1]
STAMP = "2026-10-16T18:30:00+08:00"


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        copytree(ROOT / "tests/fixtures/data", self.data)
        self.state = self.root / "state"
        self.path = self.root / "queue.json"
        self.queue = load_json(ROOT / "examples/ingestion.json")
        self.save()
        self.source = JsonObservationSource(self.path)
        self.before = read_data(self.data)

    def save(self):
        atomic_json(self.queue, self.path)

    def run_import(self, **kwargs):
        return import_queue(self.source, self.data, self.state, timestamp=STAMP, **kwargs)

    def bundle(self):
        store = IngestionStore(self.state / "ingestion.db")
        try:
            return load_json(Path(store.get(self.queue["posts"][0]["ingestion_id"])["proposal"]))
        finally:
            store.close()

    def test_update_proposal_uses_existing_merge_and_never_writes_production(self):
        result = self.run_import()
        self.assertEqual(result[0]["result"], "review")
        bundle = self.bundle()
        event = next(event for event in bundle["schedule"]["events"] if event["id"] == "demo-miri-20261016-2000-001")
        self.assertEqual(event["time"], "21:00")
        self.assertEqual(bundle["revisions"][-1]["before"]["time"], "20:00")
        self.assertEqual(read_data(self.data), self.before)
        apply_proposal(bundle, self.data, self.root / "backups", approve=True)
        self.assertEqual(read_data(self.data)["posts"][-1]["post_id"], "fixture-sheet-change")

    def test_repeated_import_and_sheet_write_failure_reuse_identical_proposal(self):
        original = self.source.update
        def update(ingestion_id, **updates):
            if updates["status"] == "review":
                raise ServiceError("Sheet")
            original(ingestion_id, **updates)
        with patch.object(self.source, "update", side_effect=update):
            self.assertEqual(self.run_import()[0]["result"], "failed")
        output = self.state / self.queue["posts"][0]["ingestion_id"] / "current/proposal.json"
        before = output.read_bytes()
        self.assertTrue(self.run_import()[0]["reused"])
        self.assertEqual(self.source.read().posts[0]["status"], "review")
        self.assertTrue(self.run_import()[0]["reused"])
        self.assertEqual(output.read_bytes(), before)
        self.assertEqual(read_data(self.data), self.before)

    def test_interrupted_processing_resumes_from_persisted_proposal(self):
        self.run_import()
        store = IngestionStore(self.state / "ingestion.db")
        store.finish(self.queue["posts"][0]["ingestion_id"], "processing", STAMP, "processing")
        store.close()
        self.queue["posts"][0]["status"] = "processing"
        self.save()
        with patch("ingestion.importer.process_fixture", side_effect=AssertionError("must reuse")):
            self.assertEqual(self.run_import()[0]["result"], "review")

    def test_processing_state_write_failure_is_retryable(self):
        with patch.object(self.source, "update", side_effect=ServiceError("Sheet")):
            self.assertEqual(self.run_import()[0]["result"], "failed")
        self.assertEqual(self.run_import()[0]["result"], "review")

    def test_dedupe_pending_proposal_by_post_and_url(self):
        self.run_import()
        for use_url in (False, True):
            with self.subTest(use_url=use_url):
                row = deepcopy(self.queue["posts"][0])
                row["ingestion_id"] = str(uuid4())
                if use_url:
                    row["post_id"] = "another-id"
                else:
                    row["source_url"] += "/another"
                self.queue["posts"].append(row)
                self.save()
                self.assertEqual(self.run_import()[-1]["result"], "duplicate")
        self.assertEqual(len(list(self.state.glob("*/*/proposal.json"))), 1)

    def test_production_post_dedupe_uses_url_fallback(self):
        post = self.before["posts"][0]
        self.queue["posts"][0].update(source_url=post["source_url"], post_id="")
        self.save()
        self.assertEqual(self.run_import()[0]["result"], "duplicate")

    def test_invalid_schema_and_cross_member_fail_without_production_write(self):
        for field, value in (("time", "25:00"), ("member_id", "demo-snow"), ("confidence", "NaN"), ("confidence", True)):
            with self.subTest(field=field):
                self.queue = load_json(ROOT / "examples/ingestion.json")
                self.queue["changes"][0][field] = value
                self.save()
                self.assertEqual(self.run_import()[0]["result"], "failed")
                self.assertEqual(self.source.read().posts[0]["status"], "failed")
        self.assertEqual(read_data(self.data), self.before)

    def test_duplicate_ingestion_ids_and_indexes_rejected(self):
        self.queue["posts"].append(deepcopy(self.queue["posts"][0]))
        self.save()
        with self.assertRaises(ValidationError):
            self.run_import()
        self.queue["posts"].pop()
        self.queue["changes"].append(deepcopy(self.queue["changes"][0]))
        self.save()
        self.assertEqual(self.run_import()[0]["result"], "failed")

    def test_ambiguous_match_becomes_unresolved_review_and_cannot_apply(self):
        values = deepcopy(self.before)
        event = deepcopy(values["schedule"]["events"][0])
        event["id"] = "another-event"
        values["schedule"]["events"].append(event)
        atomic_json(values["schedule"], self.data / "schedule.json")
        self.queue["changes"][0]["match_event_id"] = ""
        self.save()
        self.assertEqual(self.run_import()[0]["result"], "review")
        self.assertEqual(self.bundle()["merge_error"], "事件比對不明確，請指定 event id")
        with self.assertRaises(ValidationError):
            apply_proposal(self.bundle(), self.data, self.root / "backups", approve=True)
        self.assertEqual(read_data(self.data), values)

    def test_insert_day_off_cancel_and_ignore(self):
        for operation in ("insert", "cancel", "ignore"):
            with self.subTest(operation=operation):
                self.queue = load_json(ROOT / "examples/ingestion.json")
                self.queue["posts"][0]["ingestion_id"] = str(uuid4())
                self.queue["posts"][0]["post_id"] = operation
                self.queue["posts"][0]["source_url"] += "/" + operation
                change = self.queue["changes"][0]
                change.update(ingestion_id=self.queue["posts"][0]["ingestion_id"], operation=operation)
                if operation == "insert":
                    self.queue["posts"][0]["classification"] = "day_off"
                    change.update(date="2026-10-25", title="休息", time="", status="day_off")
                elif operation == "cancel":
                    self.queue["posts"][0]["classification"] = "cancellation"
                    change["time"] = ""
                else:
                    self.queue["posts"][0]["classification"] = "irrelevant"
                self.save()
                self.run_import()
                bundle = self.bundle()
                if operation == "insert":
                    self.assertEqual(bundle["schedule"]["events"][-1]["origin"], "day_off")
                elif operation == "cancel":
                    self.assertEqual(bundle["revisions"][-1]["after"]["status"], "cancelled")
                else:
                    self.assertEqual(bundle["decision"], "ignored")
                    self.assertEqual(bundle["schedule"], self.before["schedule"])

    def test_lowest_change_confidence_and_source_quality_gate_auto_apply(self):
        self.queue["changes"][0]["confidence"] = 0.6
        self.save()
        self.run_import(policy=ConfidencePolicy(review_all=False))
        self.assertEqual(self.bundle()["decision"], "record_only")
        self.assertEqual(self.bundle()["schedule"], self.before["schedule"])
        self.assertEqual(self.source.read().posts[0]["status"], "review")

    def test_secondary_source_stays_review_during_apply_with_auto_policy(self):
        self.run_import(policy=ConfidencePolicy(review_all=False))
        self.assertEqual(self.bundle()["decision"], "review")
        with self.assertRaises(ValidationError):
            apply_proposal(self.bundle(), self.data, self.root / "backups", policy=ConfidencePolicy(review_all=False))
        bundle = self.bundle()
        bundle["proposal"]["confidence"] = 1
        with self.assertRaises(ValidationError):
            apply_proposal(bundle, self.data, self.root / "backups", approve=True)

    def test_primary_official_post_can_be_eligible_for_auto(self):
        members = deepcopy(self.before["members"])
        members[0]["x_username"] = "OfficialMiri"
        atomic_json(members, self.data / "members.json")
        self.queue["posts"][0].update(source_quality="primary", post_id="123456789", source_url="https://x.com/OfficialMiri/status/123456789")
        self.save()
        self.run_import(policy=ConfidencePolicy(review_all=False))
        self.assertEqual(self.bundle()["decision"], "auto")
        self.assertEqual(read_data(self.data)["schedule"], self.before["schedule"])

    def test_source_failure_and_empty_queue_preserve_data(self):
        with patch.object(self.source, "read", side_effect=ServiceError("Sheet")), self.assertRaises(ServiceError):
            self.run_import()
        self.queue = {"posts": [], "changes": []}
        self.save()
        self.assertEqual(self.run_import(), [])
        self.assertEqual(read_data(self.data), self.before)

    def test_lock_prevents_parallel_import(self):
        self.state.mkdir()
        with data_lock(self.state), self.assertRaises(ValidationError):
            self.run_import()

    def test_optional_publish_runs_once_and_unresolved_review_is_skipped(self):
        publisher = Mock(return_value={"result": "pending_review", "url": "https://example.com/pr"})
        self.run_import(publisher=publisher)
        self.run_import(publisher=publisher)
        publisher.assert_called_once()
        self.assertIn("pending_review", self.source.read().posts[0]["processor_result"])

    def test_explicit_retry_keeps_old_artifact_and_rebuilds_corrected_proposal(self):
        self.run_import()
        original = self.bundle()
        self.queue["changes"][0]["time"] = "22:00"
        self.save()
        result = self.run_import(retry_ingestion=self.queue["posts"][0]["ingestion_id"])
        self.assertEqual(result[0]["result"], "review")
        self.assertEqual(self.bundle()["proposal"]["changes"][0]["set"]["time"], "22:00")
        self.assertEqual(load_json(self.state / self.queue["posts"][0]["ingestion_id"] / "current/proposal.json"), original)

    def test_local_apply_updates_queue_receipt_and_prevents_publishing_again(self):
        self.run_import()
        apply_proposal(self.bundle(), self.data, self.root / "backups", approve=True)
        publisher = Mock()
        self.run_import(publisher=publisher)
        publisher.assert_not_called()
        self.assertEqual(self.source.read().posts[0]["status"], "processed")

    def test_failed_publish_retries_without_regenerating_proposal(self):
        publisher = Mock(side_effect=ServiceError("GitHub"))
        self.assertEqual(self.run_import(publisher=publisher)[-1]["result"], "failed")
        publisher.side_effect = None
        publisher.return_value = {"result": "pending_review", "url": "https://example.com/pr"}
        before = self.bundle()
        self.run_import(publisher=publisher)
        self.assertEqual(publisher.call_count, 2)
        self.assertEqual(self.bundle(), before)

    def test_merged_pr_updates_queue_to_processed(self):
        publisher = Mock(return_value={"result": "pending_review", "url": "https://example.com/pr"})
        self.run_import(publisher=publisher)
        apply_proposal(self.bundle(), self.data, self.root / "backups", approve=True)
        self.run_import(publisher=publisher)
        self.assertEqual(self.source.read().posts[0]["status"], "processed")
        publisher.assert_called_once()

    def test_modified_completed_queue_requires_explicit_retry_before_publishing(self):
        self.run_import()
        self.queue["changes"][0]["time"] = "22:00"
        self.save()
        publisher = Mock()
        self.assertEqual(self.run_import(publisher=publisher)[0]["result"], "failed")
        publisher.assert_not_called()

    def test_unresolved_review_never_publishes(self):
        self.queue["changes"][0]["match_event_id"] = "missing-event"
        self.save()
        publisher = Mock()
        self.assertEqual(self.run_import(publisher=publisher)[0]["result"], "review")
        publisher.assert_not_called()

    def test_schema_failure_can_be_corrected_and_retried(self):
        self.queue["changes"][0]["status"] = "scheduled"
        self.queue["changes"][0]["time"] = "null"
        self.save()
        self.assertEqual(self.run_import()[0]["result"], "failed")
        self.queue["changes"][0]["time"] = "21:00"
        self.save()
        self.assertEqual(self.run_import(retry_ingestion=self.queue["posts"][0]["ingestion_id"])[0]["result"], "review")

    def test_cli_offline_and_health_stale_failed_stuck(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(import_main(["--input", str(self.path), "--data-dir", str(self.data), "--state-dir", str(self.state)]), 0)
            self.assertEqual(health_main(["--data-dir", str(self.data), "--ingestion-db", str(self.state / "ingestion.db")]), 0)
        store = IngestionStore(self.state / "ingestion.db")
        store.set_meta("last_sheet_read", STAMP)
        store.set_meta("queue_counts", {"failed": 1})
        store.set_meta("processing_since", [STAMP])
        store.close()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(health_main(["--data-dir", str(self.data), "--ingestion-db", str(self.state / "ingestion.db")]), 1)
        self.assertEqual(set(json.loads(output.getvalue())["issues"]), {"google_sheets_stale", "ingestion_failed", "ingestion_stuck"})


class SheetsAdapterTests(unittest.TestCase):
    def test_get_and_status_batch_update_only_target_cells_after_row_move(self):
        row = load_json(ROOT / "examples/ingestion.json")["posts"][0]
        posts = [list(POST_COLUMNS), [], [row.get(key, "") for key in POST_COLUMNS]]
        client = GoogleSheetsObservationSource("sheet-id", "token")
        with patch.object(client, "request", side_effect=[{"values": posts}, {"values": [list(CHANGE_COLUMNS)]}, {"values": posts}, {}]) as request:
            self.assertEqual(client.read().posts[0]["post_id"], row["post_id"])
            client.update(row["ingestion_id"], status="review", processed_at=STAMP, processor_result="review")
        call = request.call_args
        self.assertEqual(call.kwargs["payload"]["valueInputOption"], "RAW")
        self.assertEqual([item["range"] for item in call.kwargs["payload"]["data"]], ["posts!L3", "posts!M3", "posts!N3"])

    def test_sheet_headers_and_numeric_post_id_fail_closed(self):
        for headers in (["ingestion_id"], list(POST_COLUMNS) + ["status"]):
            with self.assertRaises(ValidationError):
                table_rows([headers], POST_COLUMNS)
        queue = load_json(ROOT / "examples/ingestion.json")
        queue["posts"][0]["post_id"] = 1234567890123456789
        with self.assertRaises(ValidationError):
            normalize(queue["posts"][0], queue["changes"])

    def test_oauth_refresh_and_failures_never_echo_secret(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = b'{"access_token":"access"}'
        env = {"GOOGLE_CLIENT_ID": "id", "GOOGLE_CLIENT_SECRET": "secret", "GOOGLE_REFRESH_TOKEN": "refresh"}
        with patch.dict(os.environ, env, clear=True), patch("ingestion.google_sheets.build_opener", return_value=opener):
            self.assertEqual(access_token(), "access")
            opener.open.return_value.__enter__.return_value.read.return_value = b'secret'
            with self.assertRaises(ServiceError) as error:
                access_token()
            self.assertNotIn("secret", str(error.exception))
