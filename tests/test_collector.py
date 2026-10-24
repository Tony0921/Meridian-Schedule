import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
from urllib.error import HTTPError

from collector.dedupe import PostStore
from collector.events import validate_event
from collector.github_dispatch import GitHubClient
from collector.http import JsonClient, ServiceError, retry_delay
from collector.main import drain, main
from collector.reconcile import reconcile
from collector.sources import JsonlSource, XAPISource
from processor.schemas import load_json

ROOT = Path(__file__).resolve().parents[1]
EVENT = {"source": "x", "post_id": "123", "member_id": "demo-miri"}


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "collector.db"
        self.store = PostStore(self.path)
        self.addCleanup(self.store.close)
        self.members = load_json(ROOT / "tests/fixtures/data/members.json")
        self.member = self.members[0]

    def test_persistent_dedupe_and_concurrent_claim(self):
        self.store.enqueue(EVENT, 0)
        self.store.enqueue(EVENT, 1)
        other = PostStore(self.path)
        self.addCleanup(other.close)
        self.assertEqual(self.store.claim(2), EVENT)
        self.assertIsNone(other.claim(2))
        self.store.complete(EVENT, 3)
        other.enqueue(EVENT, 4)
        self.assertIsNone(other.claim(999999))
        self.assertEqual(other.report()["counts"], {"dispatched": 1})

    def test_retry_delays_and_terminal_manual_review(self):
        self.store.enqueue(EVENT, 0)
        now = 0
        for delay in (60, 300, 1800):
            self.assertEqual(self.store.claim(now), EVENT)
            self.store.fail(EVENT, now)
            self.assertIsNone(self.store.claim(now + delay - 1))
            now += delay
        self.assertEqual(self.store.claim(now), EVENT)
        self.store.fail(EVENT, now)
        self.assertIsNone(self.store.claim(now + 100000))
        self.assertEqual(self.store.report()["counts"], {"manual_review": 1})

    def test_crashed_dispatch_lease_can_be_reclaimed(self):
        self.store.enqueue(EVENT, 0)
        self.assertEqual(self.store.claim(0), EVENT)
        self.assertIsNone(self.store.claim(119))
        self.assertEqual(self.store.claim(120), EVENT)

    def test_rate_limit_is_respected_and_one_failure_does_not_block_others(self):
        self.store.enqueue(EVENT, 0)
        second = {**EVENT, "post_id": "124"}
        self.store.enqueue(second, 0)
        dispatcher = Mock()
        dispatcher.dispatch.side_effect = [ServiceError("API", retry_after=600), None]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(drain(self.store, dispatcher, 0), 1)
        self.assertEqual(self.store.report()["counts"], {"failed": 1, "dispatched": 1})
        self.assertIsNone(self.store.claim(599))
        self.assertEqual(self.store.claim(600), EVENT)

    def test_invalid_and_conflicting_member_events_rejected(self):
        for bad in ({**EVENT, "post_id": "$(secret)"}, {**EVENT, "source": "other"}, {**EVENT, "extra": 1}):
            with self.assertRaises(ValueError):
                validate_event(bad)
        self.store.enqueue(EVENT, 0)
        with self.assertRaises(ValueError):
            self.store.enqueue({**EVENT, "member_id": "another"}, 0)

    def test_operator_can_requeue_failed_but_not_delivered_post(self):
        self.store.enqueue(EVENT, 0)
        self.store.claim(0)
        self.store.fail(EVENT, 0)
        self.store.requeue(EVENT["post_id"], 1)
        self.assertEqual(self.store.claim(1), EVENT)
        self.store.complete(EVENT, 2)
        with self.assertRaises(ValueError):
            self.store.requeue(EVENT["post_id"], 3)

    def test_reconciliation_hours_are_configurable(self):
        source = Mock()
        source.fetch_recent.return_value = []
        now = datetime.fromisoformat("2026-10-16T09:01:00+08:00").timestamp()
        self.store.scanned(self.member["id"], now - 7200)
        reconcile(source, self.store, [self.member], now, due_only=True, hours=(9, 21))
        source.fetch_recent.assert_called_once()
        with self.assertRaises(ValueError):
            reconcile(source, self.store, [self.member], now, hours=(25,))

    def test_reconcile_checkpoint_only_advances_after_complete_scan(self):
        source = Mock()
        def partial(*args):
            yield EVENT
            raise ServiceError("pagination")
        source.fetch_recent.side_effect = partial
        now = datetime.fromisoformat("2026-10-16T06:01:00+08:00").timestamp()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(reconcile(source, self.store, [self.member], now), 1)
        self.assertIsNone(self.store.scan_time(self.member["id"]))
        source.fetch_recent.side_effect = None
        source.fetch_recent.return_value = [EVENT]
        self.assertEqual(reconcile(source, self.store, [self.member], now + 300), 0)
        self.assertEqual(self.store.scan_time(self.member["id"]), now + 300)
        self.assertEqual(self.store.report()["counts"], {"pending": 1})

    def test_daily_slots_and_overlap_without_high_frequency_polling(self):
        source = Mock()
        source.fetch_recent.return_value = []
        morning = datetime.fromisoformat("2026-10-16T06:01:00+08:00").timestamp()
        reconcile(source, self.store, [self.member], morning, due_only=True)
        reconcile(source, self.store, [self.member], morning + 3600, due_only=True)
        self.assertEqual(source.fetch_recent.call_count, 1)
        reconcile(source, self.store, [self.member], morning + 12 * 3600, due_only=True)
        self.assertEqual(source.fetch_recent.call_count, 2)
        since = datetime.fromisoformat(source.fetch_recent.call_args.args[1].replace("Z", "+00:00")).timestamp()
        self.assertEqual(since, morning - 3600)

    def test_jsonl_replay_and_collector_cli_without_network(self):
        manual = load_json(ROOT / "examples/manual-post.json")
        path = Path(self.temp.name) / "posts.jsonl"
        path.write_text("invalid\n" + json.dumps(manual) + "\n" + json.dumps(manual), encoding="utf-8")
        source = JsonlSource(path)
        self.assertEqual(source.fetch_post(manual["post"]["post_id"]), manual)
        self.assertEqual(len(list(source.fetch_recent(self.member, "2020-01-01T00:00:00Z"))), 2)
        client = Mock()
        with patch("collector.main.create_source", return_value=source), patch("collector.main.GitHubClient", return_value=client), redirect_stdout(io.StringIO()):
            self.assertEqual(main(["listen", "--once", "--source", "jsonl", "--members", str(ROOT / "tests/fixtures/data/members.json"),
                                   "--db", str(Path(self.temp.name) / "cli.db")]), 0)
        client.dispatch.assert_called_once()


class SourceAndHTTPTests(unittest.TestCase):
    def setUp(self):
        self.members = [{"id": "miri", "enabled": True, "x_username": "Miri_Aetris"}]
        self.source = XAPISource(self.members, "test-only-token")
        self.envelope = {"data": {"id": "123", "author_id": "456", "text": "週表", "created_at": "2026-10-16T00:00:00Z",
                                   "attachments": {"media_keys": ["photo1"]}},
                         "includes": {"users": [{"id": "456", "username": "Miri_Aetris"}],
                                      "media": [{"media_key": "photo1", "type": "photo", "url": "https://pbs.twimg.com/media/test.png"}]}}

    def test_x_lookup_preserves_author_text_and_media(self):
        self.source.request = Mock(return_value=self.envelope)
        manual = self.source.fetch_post("123")
        self.assertEqual(manual["post"]["member_id"], "miri")
        self.assertEqual(manual["post"]["media"][0]["url"], "https://pbs.twimg.com/media/test.png")
        self.assertEqual(manual["post_text"], "週表")
        self.envelope["includes"]["users"][0]["username"] = "someoneelse"
        with self.assertRaises(ServiceError):
            self.source.fetch_post("123")

    def test_x_timeline_paginates_and_failure_does_not_look_complete(self):
        self.source.request = Mock(side_effect=[{"data": {"id": "456"}}, {"data": [{"id": "123"}], "meta": {"next_token": "next"}},
                                               {"data": [{"id": "124"}]}])
        events = list(self.source.fetch_recent(self.members[0], "2026-10-15T00:00:00Z"))
        self.assertEqual([e["post_id"] for e in events], ["123", "124"])
        self.assertIn("pagination_token=next", self.source.request.call_args.args[0])

    def test_stream_keepalive_and_bad_post_do_not_end_listener(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.readline.side_effect = [b"\r\n", b"bad\n", json.dumps(self.envelope).encode() + b"\n", b""]
        with patch("collector.sources.build_opener", return_value=opener):
            self.assertEqual(list(self.source.listen()), [None, {"source": "x", "post_id": "123", "member_id": "miri"}])

    def test_rule_setup_adds_only_missing_rules(self):
        self.source.request = Mock(return_value={"data": [{"value": "from:miri_aetris -is:retweet"}]})
        self.source.setup_rules()
        self.source.request.assert_called_once()

    def test_dispatch_payload_contains_only_validated_metadata(self):
        client = GitHubClient("owner/repo", "test-only-token")
        client.request = Mock()
        client.dispatch(EVENT)
        self.assertEqual(client.request.call_args.kwargs["payload"], {"event_type": "new_x_post", "client_payload": EVENT})

    def test_http_errors_hide_secrets_and_honor_retry_after(self):
        opener = MagicMock()
        opener.open.side_effect = HTTPError("https://api.x.com", 429, "test-only-token", {"Retry-After": "300"}, io.BytesIO(b"test-only-token"))
        with patch("collector.http.build_opener", return_value=opener), self.assertRaises(ServiceError) as error:
            JsonClient("https://api.x.com", "test-only-token").request("/2/tweets/123")
        self.assertEqual(error.exception.retry_after, 300)
        self.assertNotIn("test-only-token", str(error.exception))

    def test_x_rate_reset_and_http_date_are_respected(self):
        self.assertEqual(retry_delay({"x-rate-limit-reset": "1000", "Retry-After": "60"}, now=100), 900)
        self.assertEqual(retry_delay({"Retry-After": "Thu, 01 Jan 1970 00:10:00 GMT"}, now=100), 500)
        self.assertEqual(retry_delay({"Retry-After": "invalid"}, now=100), 0)
