import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from shutil import copytree
from unittest.mock import MagicMock, Mock, patch

from collector.http import ServiceError
from processor.classify import ConfidencePolicy
from processor.media import download_images
from processor.schemas import load_json
from processor.storage import atomic_json, read_data
from scripts.health_check import main as health_main
from scripts.process_event import process_event
from scripts.process_post import process_fixture
from scripts.publish_proposal import publish

ROOT = Path(__file__).resolve().parents[1]
STAMP = "2026-10-16T18:30:00+08:00"
PNG = b"\x89PNG\r\n\x1a\nexample"


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        copytree(ROOT / "tests/fixtures/data", self.data)
        self.fixture = load_json(ROOT / "tests/fixtures/schedule-change.json")
        self.manual = {"post": self.fixture["post"], "post_text": "今天改九點", "images": []}
        self.event = {key: self.fixture["post"][key] for key in ("source", "post_id", "member_id")}
        self.source = Mock()
        self.source.fetch_post.return_value = self.manual
        self.interpreter = Mock()
        self.interpreter.extract.return_value = self.fixture["proposal"]

    def process(self, **kwargs):
        with redirect_stdout(io.StringIO()):
            return process_event(self.event, self.data, self.root / "output", self.source, self.interpreter, **kwargs)

    def test_event_fetch_parse_validate_and_review_without_production_changes(self):
        before = read_data(self.data)
        result = self.process()
        self.assertEqual(result["decision"], "review")
        self.assertEqual(read_data(self.data), before)
        self.assertEqual(load_json(self.root / "output/status.json")["classification"], "schedule_change")
        self.assertEqual(load_json(self.root / "output/source.json"), self.manual)

    def test_processor_duplicate_skips_source_and_ai(self):
        known = read_data(self.data)["posts"][0]
        self.event = {key: known[key] for key in self.event}
        self.assertIsNone(self.process())
        self.source.fetch_post.assert_not_called()
        self.interpreter.extract.assert_not_called()

    def test_mismatched_author_is_rejected_before_ai(self):
        self.manual["post"]["member_id"] = "demo-snow"
        with self.assertRaises(ValueError):
            self.process(delays=())
        self.interpreter.extract.assert_not_called()

    def test_processor_retries_and_persists_terminal_failure_without_secret(self):
        self.source.fetch_post.side_effect = ServiceError("API", retry_after=120)
        sleep = Mock()
        with self.assertRaises(ValueError):
            self.process(sleep=sleep)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [120, 300, 1800])
        status = load_json(self.root / "output/status.json")
        self.assertEqual((status["result"], status["attempt"]), ("manual_review", 4))
        self.assertFalse((self.root / "output/proposal.json").exists())

    def test_processor_recovers_transient_error(self):
        self.source.fetch_post.side_effect = [ServiceError("API"), self.manual]
        result = self.process(sleep=Mock())
        self.assertEqual(result["decision"], "review")
        self.assertEqual(load_json(self.root / "output/status.json")["attempt"], 2)

    def test_media_download_host_and_size_guard(self):
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        response.read.return_value = PNG
        with patch("processor.media.build_opener", return_value=opener):
            result = download_images(["https://pbs.twimg.com/media/test.png"])
        self.assertTrue(result[0].startswith("data:image/png;base64,"))
        for url in ("http://pbs.twimg.com/media/test", "https://127.0.0.1/a", "https://pbs.twimg.com:8443/a", "https://user:secret@pbs.twimg.com/a"):
            with self.assertRaises(ValueError):
                download_images([url])
        response.read.return_value = b"x" * (10 * 1024 * 1024 + 1)
        with patch("processor.media.build_opener", return_value=opener), self.assertRaises(ServiceError):
            download_images(["https://pbs.twimg.com/media/test.png"])

    def test_health_command_reports_data_and_missing_collector_state(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(health_main(["--data-dir", str(self.data)]), 0)
            self.assertEqual(health_main(["--data-dir", str(self.data), "--db", str(self.root / "missing.db")]), 1)

    def publisher(self, *, fail_push=False, conflicting_time=False):
        client = Mock()
        client.repository = "owner/repo"
        client._token = "test-only-token"
        client.pending_pr.return_value = None
        client.create_pr.return_value = {"html_url": "https://github.com/owner/repo/pull/1"}
        calls, pushed = [], []
        def fake_git(*args, cwd, env):
            calls.append(args)
            self.assertNotIn("test-only-token", " ".join(args))
            if args[:2] == ("worktree", "add"):
                checkout = Path(args[3])
                checkout.mkdir()
                copytree(self.data, checkout / "data")
            if args[0] == "push":
                pushed.append(read_data(Path(cwd) / "data"))
                if fail_push and len(pushed) == 1:
                    latest = read_data(self.data)
                    latest["schedule"]["events"][0]["time" if conflicting_time else "title"] = "22:00" if conflicting_time else "另一篇貼文更新的標題"
                    atomic_json(latest["schedule"], self.data / "schedule.json")
                    raise ServiceError("push conflict")
            return ""
        return client, fake_git, calls, pushed

    def test_default_publisher_creates_pr_from_revalidated_data(self):
        bundle = process_fixture(self.fixture, self.data, STAMP)
        client, fake_git, calls, pushed = self.publisher()
        with patch("scripts.publish_proposal.git", side_effect=fake_git):
            result = publish(bundle, self.root, client)
        self.assertEqual(result["result"], "pending_review")
        event = next(event for event in pushed[0]["schedule"]["events"] if event["id"] == "demo-miri-20261016-2000-001")
        self.assertEqual(event["time"], "21:00")
        self.assertTrue(any(call[0] == "push" and "refs/heads/codex/post-" in call[-1] for call in calls))
        self.assertFalse(any("force" in argument for call in calls for argument in call))
        client.create_pr.assert_called_once()

    def test_auto_push_conflict_reloads_latest_and_preserves_other_changes(self):
        bundle = process_fixture(self.fixture, self.data, STAMP)
        client, fake_git, calls, pushed = self.publisher(fail_push=True)
        with patch("scripts.publish_proposal.git", side_effect=fake_git):
            result = publish(bundle, self.root, client, policy=ConfidencePolicy(review_all=False))
        self.assertEqual(result["result"], "auto")
        self.assertEqual(len(pushed), 2)
        event = next(event for event in pushed[-1]["schedule"]["events"] if event["id"] == "demo-miri-20261016-2000-001")
        self.assertEqual(event["title"], "另一篇貼文更新的標題")
        self.assertEqual(event["time"], "21:00")
        client.create_pr.assert_not_called()

    def test_pending_pr_short_circuits_without_duplicate_push(self):
        bundle = process_fixture(self.fixture, self.data, STAMP)
        client, fake_git, calls, pushed = self.publisher()
        client.pending_pr.return_value = {"html_url": "https://github.com/owner/repo/pull/1"}
        with patch("scripts.publish_proposal.git", side_effect=fake_git):
            self.assertEqual(publish(bundle, self.root, client)["result"], "pending_review")
        self.assertFalse(pushed)
        client.create_pr.assert_not_called()

    def test_push_conflict_does_not_overwrite_newer_change_to_same_field(self):
        bundle = process_fixture(self.fixture, self.data, STAMP)
        client, fake_git, _, pushed = self.publisher(fail_push=True, conflicting_time=True)
        with patch("scripts.publish_proposal.git", side_effect=fake_git), self.assertRaises(ValueError):
            publish(bundle, self.root, client, policy=ConfidencePolicy(review_all=False))
        self.assertEqual(len(pushed), 1)
        self.assertEqual(read_data(self.data)["schedule"]["events"][0]["time"], "22:00")

    def test_low_confidence_publication_records_post_without_schedule_change(self):
        fixture = load_json(ROOT / "tests/fixtures/uncertain.json")
        before = read_data(self.data)
        client, fake_git, _, pushed = self.publisher()
        with patch("scripts.publish_proposal.git", side_effect=fake_git):
            result = publish(process_fixture(fixture, self.data, STAMP), self.root, client)
        self.assertEqual(result["result"], "record_only")
        self.assertEqual(pushed[0]["schedule"], before["schedule"])
        self.assertEqual(pushed[0]["posts"][-1]["status"], "manual_review")
