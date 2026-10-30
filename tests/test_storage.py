import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path
from shutil import copytree
from unittest.mock import patch

from processor.schemas import ValidationError, load_json
from processor.storage import (NAMES, atomic_json, data_lock, load_snapshot, read_data,
                               recover_unlocked, snapshot, write_data_unlocked)
from scripts.backup_data import main as backup_main

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

    def candidate(self):
        values = read_data(self.directory)
        event = values["schedule"]["events"][0]
        before = deepcopy(event)
        event.update(time="21:00", updated_at=STAMP)
        values["schedule"]["updated_at"] = STAMP
        values["revisions"].append({"event_id": event["id"], "timestamp": STAMP,
                                   "source_post_id": event["source_post_id"],
                                   "before": before, "after": deepcopy(event)})
        return values

    def assert_original(self):
        self.assertEqual(self.before, {name: (self.directory / f"{name}.json").read_bytes() for name in NAMES})

    def test_write_creates_verified_backup_and_full_revision(self):
        candidate = self.candidate()
        with data_lock(self.directory):
            backup_path = write_data_unlocked(self.directory, candidate, self.backups)
        backup = load_snapshot(backup_path)
        self.assertEqual(backup["data"]["schedule"]["events"][0]["time"], "20:00")
        current = read_data(self.directory)
        event = current["schedule"]["events"][0]
        self.assertEqual(event["time"], "21:00")
        self.assertEqual(current["posts"], json.loads(self.before["posts"]))
        self.assertEqual(len(current["revisions"]), 1)
        self.assertEqual(current["revisions"][0]["before"], json.loads(self.before["schedule"])["events"][0])
        self.assertEqual(current["revisions"][0]["after"], event)

    def test_invalid_candidate_does_not_write_or_create_backup(self):
        candidate = self.candidate()
        candidate["schedule"]["events"][0]["member_id"] = "missing-member"
        with data_lock(self.directory), self.assertRaises(ValidationError):
            write_data_unlocked(self.directory, candidate, self.backups)
        self.assert_original()
        self.assertFalse(self.backups.exists())

    def test_partial_write_rolls_back_original_bytes(self):
        candidate = self.candidate()
        real = atomic_json
        def fail_on_schedule(value, path):
            if Path(path).name == "schedule.json":
                raise OSError("simulated full disk")
            real(value, path)
        with data_lock(self.directory), patch("processor.storage.atomic_json", side_effect=fail_on_schedule), self.assertRaises(OSError):
            write_data_unlocked(self.directory, candidate, self.backups)
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
        candidate = self.candidate()
        with data_lock(self.directory):
            backup_path = write_data_unlocked(self.directory, candidate, self.backups)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(backup_main(["restore", "--snapshot", str(backup_path), "--data-dir", str(self.directory),
                                          "--backup-dir", str(self.backups)]), 0)
        self.assertEqual(read_data(self.directory)["schedule"], json.loads(self.before["schedule"]))
        corrupted = load_json(backup_path)
        corrupted["data"]["schedule"]["events"].clear()
        atomic_json(corrupted, backup_path)
        with self.assertRaises(ValidationError):
            load_snapshot(backup_path)
        self.assertEqual(len(list(self.backups.glob("*.json"))), 2)

    def test_file_lock_and_backup_directory_protection(self):
        with data_lock(self.directory):
            with self.assertRaises(ValidationError):
                read_data(self.directory)
        candidate = self.candidate()
        with data_lock(self.directory), self.assertRaises(ValidationError):
            write_data_unlocked(self.directory, candidate, self.directory / "backups")
        self.assert_original()
