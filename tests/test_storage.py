import json
import tempfile
import unittest
from pathlib import Path
from shutil import copytree
from unittest.mock import patch

from processor.classify import ConfidencePolicy
from processor.schemas import ValidationError, load_json
from processor.storage import (NAMES, atomic_json, data_lock, load_snapshot, read_data,
                               recover_unlocked, snapshot)
from scripts.apply_proposal import apply_proposal
from scripts.backup_data import main as backup_main
from scripts.process_post import process_fixture

ROOT = Path(__file__).resolve().parents[1]
STAMP = "2026-10-16T18:30:00+08:00"


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "data"
        copytree(ROOT / "tests/fixtures/data", self.directory)
        self.backups = Path(self.temp.name) / "backups"
        self.before = {name: (self.directory / f"{name}.json").read_bytes() for name in NAMES}

    def bundle(self, name="schedule-change"):
        return process_fixture(load_json(ROOT / "tests/fixtures" / f"{name}.json"), self.directory, STAMP)

    def assert_original(self):
        self.assertEqual(self.before, {name: (self.directory / f"{name}.json").read_bytes() for name in NAMES})

    def test_review_requires_approval_and_creates_verified_backup(self):
        bundle = self.bundle()
        with self.assertRaises(ValidationError):
            apply_proposal(bundle, self.directory, self.backups)
        self.assert_original()
        result = apply_proposal(bundle, self.directory, self.backups, approve=True)
        backup = load_snapshot(result["backup"])
        self.assertEqual(backup["data"]["schedule"]["events"][0]["time"], "20:00")
        current = read_data(self.directory)
        event = next(event for event in current["schedule"]["events"] if event["id"] == "demo-miri-20261016-2000-001")
        self.assertEqual(event["time"], "21:00")
        self.assertEqual(current["posts"][-1]["status"], "processed")
        self.assertEqual(len(current["revisions"]), 1)

    def test_tampered_candidate_is_ignored_and_remerged(self):
        bundle = self.bundle()
        bundle["schedule"]["events"].clear()
        bundle["members"].clear()
        apply_proposal(bundle, self.directory, self.backups, approve=True)
        self.assertTrue(read_data(self.directory)["schedule"]["events"])

    def test_stale_and_duplicate_proposals_cannot_overwrite_data(self):
        stale = self.bundle()
        apply_proposal(self.bundle("sudden-stream"), self.directory, self.backups, approve=True)
        current = read_data(self.directory)
        with self.assertRaises(ValidationError):
            apply_proposal(stale, self.directory, self.backups, approve=True)
        self.assertEqual(read_data(self.directory), current)
        with self.assertRaises(ValidationError):
            apply_proposal(self.bundle("sudden-stream"), self.directory, self.backups, approve=True)

    def test_low_confidence_approval_only_records_manual_review(self):
        old = read_data(self.directory)
        apply_proposal(self.bundle("uncertain"), self.directory, self.backups, approve=True)
        current = read_data(self.directory)
        self.assertEqual(current["schedule"], old["schedule"])
        self.assertEqual(current["revisions"], old["revisions"])
        self.assertEqual(current["posts"][-1]["status"], "manual_review")

    def test_explicit_auto_policy_applies_high_confidence(self):
        apply_proposal(self.bundle(), self.directory, self.backups, policy=ConfidencePolicy(review_all=False))
        self.assertEqual(read_data(self.directory)["posts"][-1]["status"], "processed")

    def test_partial_write_rolls_back_original_bytes(self):
        real = atomic_json
        def fail_on_schedule(value, path):
            if Path(path).name == "schedule.json":
                raise OSError("simulated full disk")
            real(value, path)
        with patch("processor.storage.atomic_json", side_effect=fail_on_schedule), self.assertRaises(OSError):
            apply_proposal(self.bundle(), self.directory, self.backups, approve=True)
        self.assert_original()
        self.assertFalse((self.directory / ".transaction.json").exists())

    def test_interrupted_transaction_blocks_reads_and_can_recover(self):
        with data_lock(self.directory):
            backup = snapshot(self.directory, self.backups)
        atomic_json(load_json(backup), self.directory / ".transaction.json")
        (self.directory / "schedule.json").write_text("broken", encoding="utf-8")
        with self.assertRaises(ValidationError):
            read_data(self.directory)
        with data_lock(self.directory):
            self.assertTrue(recover_unlocked(self.directory))
            self.assertFalse(recover_unlocked(self.directory))
        self.assert_original()

    def test_backup_tampering_rejected_and_restore_preserves_current_backup(self):
        result = apply_proposal(self.bundle(), self.directory, self.backups, approve=True)
        import io
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()):
            self.assertEqual(backup_main(["restore", "--snapshot", result["backup"], "--data-dir", str(self.directory),
                                          "--backup-dir", str(self.backups)]), 0)
        self.assertEqual(read_data(self.directory)["schedule"], json.loads(self.before["schedule"]))
        corrupted = load_json(Path(result["backup"]))
        corrupted["data"]["schedule"]["events"].clear()
        atomic_json(corrupted, Path(result["backup"]))
        with self.assertRaises(ValidationError):
            load_snapshot(result["backup"])
        self.assertEqual(len(list(self.backups.glob("*.json"))), 2)

    def test_file_lock_and_backup_directory_protection(self):
        with data_lock(self.directory):
            with self.assertRaises(ValidationError):
                read_data(self.directory)
        with self.assertRaises(ValidationError):
            apply_proposal(self.bundle(), self.directory, self.directory / "backups", approve=True)
        self.assert_original()
