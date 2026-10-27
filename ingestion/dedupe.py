"""SQLite 匯入 receipt；在 Sheet 回寫前保存結果，重試沿用同一份提案。"""

import json
import sqlite3
from pathlib import Path

from ingestion.normalize import canonical_url, source_identity


class IngestionStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=0)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS ingestion (
                ingestion_id TEXT PRIMARY KEY, source TEXT NOT NULL, external_post_id TEXT NOT NULL,
                source_url TEXT NOT NULL, payload_hash TEXT NOT NULL, status TEXT NOT NULL,
                discovered_at TEXT NOT NULL, processed_at TEXT NOT NULL, proposal TEXT,
                processor_result TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0,
                UNIQUE(source, external_post_id), UNIQUE(source_url)
            );
            CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)

    def close(self):
        self.db.close()

    def get(self, ingestion_id):
        row = self.db.execute("SELECT * FROM ingestion WHERE ingestion_id=?", (ingestion_id,)).fetchone()
        return dict(row) if row else None

    def duplicate(self, observation):
        return self.db.execute("SELECT ingestion_id FROM ingestion WHERE (source=? AND external_post_id=?) OR source_url=?",
                               (observation["source"], source_identity(observation), canonical_url(observation["source_url"]))).fetchone()

    def reserve(self, observation, payload_hash, timestamp, proposal):
        with self.db:
            self.db.execute("INSERT INTO ingestion (ingestion_id,source,external_post_id,source_url,payload_hash,status,discovered_at,processed_at,processor_result,proposal) VALUES (?,?,?,?,?,'processing',?,?,'processing',?)",
                            (observation["ingestion_id"], observation["source"], source_identity(observation),
                             canonical_url(observation["source_url"]), payload_hash, observation["discovered_at"], timestamp, str(proposal)))

    def retry(self, ingestion_id):
        receipt = self.get(ingestion_id)
        if not receipt or receipt["published"] or receipt["status"] not in {"review", "failed"}:
            raise ValueError("只能重產尚未發布的 review / failed 提案")
        with self.db:
            self.db.execute("DELETE FROM ingestion WHERE ingestion_id=?", (ingestion_id,))

    def finish(self, ingestion_id, status, timestamp, result, proposal=None):
        with self.db:
            self.db.execute("UPDATE ingestion SET status=?,processed_at=?,processor_result=?,proposal=COALESCE(?,proposal) WHERE ingestion_id=?",
                            (status, timestamp, result, str(proposal) if proposal else None, ingestion_id))

    def unpublished(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM ingestion WHERE proposal IS NOT NULL AND published=0 AND status IN ('review','processed')")]

    def published(self, ingestion_id, result, timestamp):
        status = "review" if result["result"] == "pending_review" else "processed"
        with self.db:
            self.db.execute("UPDATE ingestion SET published=1,status=?,processed_at=?,processor_result=? WHERE ingestion_id=?",
                            (status, timestamp, json.dumps(result, ensure_ascii=False), ingestion_id))
        if result["result"] != "duplicate":
            self.set_meta("last_git_push", timestamp)

    def set_meta(self, name, value):
        with self.db:
            self.db.execute("INSERT INTO metadata VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                            (name, json.dumps(value)))

    def report(self):
        metadata = {row["name"]: json.loads(row["value"]) for row in self.db.execute("SELECT * FROM metadata")}
        metadata["local_processing_since"] = [row["processed_at"] for row in self.db.execute("SELECT processed_at FROM ingestion WHERE status='processing'")]
        metadata["local_counts"] = {row["status"]: row["count"] for row in self.db.execute("SELECT status,COUNT(*) AS count FROM ingestion GROUP BY status")}
        return metadata
