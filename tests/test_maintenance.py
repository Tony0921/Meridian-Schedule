import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from shutil import copy2, copytree


ROOT = Path(__file__).resolve().parents[1]


class StandaloneMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for package, names in {
            "ingestion": ("__init__", "schedule_csv"),
            "processor": ("__init__", "models", "schemas", "validate", "storage"),
            "scripts": ("__init__", "backup_data", "health_check", "import_schedule", "validate_data"),
        }.items():
            (self.root / package).mkdir()
            for name in names:
                copy2(ROOT / package / f"{name}.py", self.root / package / f"{name}.py")
        copytree(ROOT / "schemas", self.root / "schemas")
        copytree(ROOT / "tests/fixtures/data", self.root / "data")
        self.csv = self.root / "schedule.csv"
        copy2(ROOT / "examples/schedule-ingestion.csv", self.csv)

    def invoke(self, module, *arguments):
        return subprocess.run([sys.executable, "-B", "-m", module, *arguments], cwd=self.root,
                              env={**os.environ, "PYTHONPATH": str(self.root), "PYTHONIOENCODING": "utf-8"},
                              capture_output=True, text=True, encoding="utf-8")

    def command(self, module, *arguments):
        result = self.invoke(module, *arguments)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        self.assertTrue(result.stdout.strip(), result.stderr)
        return result.returncode, json.loads(result.stdout)

    def test_csv_import_history_validation_and_noop_with_only_core_modules(self):
        code, result = self.command("scripts.import_schedule", "--input", str(self.csv))
        self.assertEqual((code, result["imported"], result["invalid"], result["changed"]), (0, 3, 0, True))
        data = self.root / "data"
        expected_ids = {"demo-miri_20261028_01", "demo-miri_20261029_01", "demo-snow_20261028_01"}
        revisions = json.loads((data / "revisions.json").read_text(encoding="utf-8"))
        self.assertEqual({revision["event_id"] for revision in revisions}, expected_ids)
        self.assertTrue(all(revision["before"] is None and revision["after"]["id"] == revision["event_id"]
                            for revision in revisions))
        self.assertEqual(set(json.loads((data / "imported_ids.json").read_text(encoding="utf-8"))), expected_ids)
        validated = self.invoke("scripts.validate_data")
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertIn("資料驗證通過", validated.stdout)
        self.assertEqual(self.command("scripts.health_check")[0], 0)
        before = {path.name: path.read_bytes() for path in data.glob("*.json")}
        backups = self.root / ".local/backups"
        self.assertEqual(len(list(backups.glob("*.json"))), 1)
        code, result = self.command("scripts.import_schedule", "--input", str(self.csv))
        self.assertEqual((code, result["imported"], result["duplicates"], result["changed"]), (0, 0, 3, False))
        self.assertEqual({path.name: path.read_bytes() for path in data.glob("*.json")}, before)
        self.assertEqual(len(list(backups.glob("*.json"))), 1)

    def test_backup_restore_and_recover_without_parser_or_legacy_sources(self):
        before = {path.name: path.read_bytes() for path in (self.root / "data").glob("*.json")}
        code, result = self.command("scripts.backup_data", "backup")
        self.assertEqual((code, result["result"]), (0, "success"))
        snapshot = result["backup"]
        schedule = self.root / "data/schedule.json"
        changed = json.loads(schedule.read_text(encoding="utf-8"))
        changed["events"][0]["title"] = "人工修正後的標題"
        schedule.write_text(json.dumps(changed), encoding="utf-8")
        code, result = self.command("scripts.backup_data", "restore", "--snapshot", snapshot)
        self.assertEqual((code, result["result"]), (0, "success"))
        self.assertEqual({path.name: json.loads(path.read_text(encoding="utf-8"))
                          for path in (self.root / "data").glob("*.json")},
                         {**{name: json.loads(body) for name, body in before.items()}, "imported_ids.json": []})
        code, result = self.command("scripts.backup_data", "recover")
        self.assertEqual((code, result["result"], result["backup"]), (0, "success", False))

    def test_health_check_without_parser_or_legacy_sources(self):
        code, result = self.command("scripts.health_check")
        self.assertEqual((code, result), (0, {"result": "healthy", "issues": [], "manual_review_posts": 0}))
        path = self.root / "data/posts.json"
        posts = json.loads(path.read_text(encoding="utf-8"))
        posts[0]["status"] = "manual_review"
        path.write_text(json.dumps(posts), encoding="utf-8")
        code, result = self.command("scripts.health_check")
        self.assertEqual((code, result), (1, {"result": "unhealthy", "issues": ["posts_need_review"], "manual_review_posts": 1}))

    def test_health_check_reports_invalid_data_without_legacy_sources(self):
        (self.root / "data/schedule.json").write_text("invalid JSON", encoding="utf-8")
        code, result = self.command("scripts.health_check")
        self.assertEqual((code, result), (1, {"result": "unhealthy", "issues": ["invalid_data_or_state"]}))
