import tempfile
import unittest
from pathlib import Path
from shutil import copytree
from unittest.mock import MagicMock, patch

from collector.x_public import XPublicSource
from processor.schemas import load_json
from processor.storage import atomic_json, read_data
from scripts.reconcile_posts import reconcile_posts

ROOT = Path(__file__).resolve().parents[1]
STAMP = "2026-10-16T18:30:00+08:00"
RSS = b'''<rss version="2.0"><channel><item>
<link>https://feed.example/OfficialMiri/status/123456789</link>
<pubDate>Fri, 16 Oct 2026 09:00:00 GMT</pubDate>
<description>Tonight 21:00</description>
</item></channel></rss>'''


class PublicReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        copytree(ROOT / "tests/fixtures/data", self.data)
        members = load_json(self.data / "members.json")
        members[0]["x_username"] = "OfficialMiri"
        atomic_json(members, self.data / "members.json")
        self.before = read_data(self.data)
        self.output = self.root / "queue/missing.json"
        self.source = XPublicSource(members, {"demo-miri": "https://feed.example/miri/rss"})
        self.opener = MagicMock()
        self.opener.open.return_value.__enter__.return_value.read.return_value = RSS

    def run_reconcile(self):
        with patch("collector.x_public.build_opener", return_value=self.opener):
            return reconcile_posts(self.source, self.data, self.output, timestamp=STAMP)

    def test_public_feed_outputs_raw_queue_once_without_ai_or_production_writes(self):
        self.assertEqual(self.run_reconcile()["missing_posts"], 1)
        self.assertEqual(self.run_reconcile()["missing_posts"], 1)
        state = load_json(self.output)
        self.assertEqual(state["posts"][0]["source_quality"], "secondary")
        self.assertEqual(state["posts"][0]["post"]["source_url"], "https://x.com/OfficialMiri/status/123456789")
        self.assertEqual(read_data(self.data), self.before)

    def test_failure_preserves_prior_queue_and_checkpoint(self):
        self.run_reconcile()
        before = load_json(self.output)
        self.opener.open.side_effect = OSError("secret")
        self.assertEqual(self.run_reconcile()["result"], "failed")
        after = load_json(self.output)
        self.assertEqual(after["posts"], before["posts"])
        self.assertEqual(after["scans"], before["scans"])
        self.assertNotIn("secret", str(after))
        self.assertEqual(read_data(self.data), self.before)

    def test_missing_feed_fails_without_paid_api_fallback(self):
        self.source.feeds = {}
        self.assertEqual(self.run_reconcile()["result"], "failed")
        self.opener.open.assert_not_called()

    def test_wrong_author_and_empty_feed_do_not_cancel_existing_events(self):
        self.opener.open.return_value.__enter__.return_value.read.return_value = RSS.replace(b"OfficialMiri", b"AnotherAuthor")
        self.assertEqual(self.run_reconcile()["missing_posts"], 0)
        self.opener.open.return_value.__enter__.return_value.read.return_value = b'<rss><channel/></rss>'
        self.assertEqual(self.run_reconcile()["missing_posts"], 0)
        self.assertEqual(read_data(self.data), self.before)

    def test_partial_feed_failure_never_advances_checkpoint(self):
        broken = RSS.replace(b"</channel>", b'<item><link>https://feed.example/OfficialMiri/status/222</link><pubDate>bad</pubDate></item></channel>')
        self.opener.open.return_value.__enter__.return_value.read.return_value = broken
        self.assertEqual(self.run_reconcile()["result"], "failed")
        self.assertEqual(load_json(self.output)["scans"], {})
        self.assertEqual(load_json(self.output)["posts"], [])
