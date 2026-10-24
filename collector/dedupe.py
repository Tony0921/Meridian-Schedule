"""持久化 outbox：可重送失敗項目，已送出項目不再 dispatch。"""

import sqlite3
from pathlib import Path

from collector.events import validate_event

RETRY_DELAYS = (60, 300, 1800)


class PostStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS posts (
                source TEXT NOT NULL, post_id TEXT NOT NULL, member_id TEXT NOT NULL,
                detected_at REAL NOT NULL, dispatched_at REAL, status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
                lease_until REAL NOT NULL DEFAULT 0, PRIMARY KEY(source, post_id)
            );
            CREATE TABLE IF NOT EXISTS scans (member_id TEXT PRIMARY KEY, completed_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS health (name TEXT PRIMARY KEY, updated_at REAL NOT NULL);
        """)

    def close(self):
        self.db.close()

    def enqueue(self, event, now):
        event = validate_event(event)
        with self.db:
            existing = self.db.execute("SELECT member_id FROM posts WHERE source=? AND post_id=?",
                                       (event["source"], event["post_id"])).fetchone()
            if existing and existing["member_id"] != event["member_id"]:
                raise ValueError("同一貼文不可屬於不同成員")
            self.db.execute("INSERT OR IGNORE INTO posts(source,post_id,member_id,detected_at,status) VALUES(?,?,?,?, 'pending')",
                            (event["source"], event["post_id"], event["member_id"], now))

    def claim(self, now, *, lease_seconds=120):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            # 中斷時無法知道遠端是否已收到；恢復後允許重送，由 Processor 再做冪等檢查。
            self.db.execute("UPDATE posts SET status='manual_review' WHERE status='dispatching' AND lease_until<=? AND attempts>=4", (now,))
            row = self.db.execute("""SELECT * FROM posts WHERE
                (status IN ('pending','failed') AND next_attempt<=?) OR
                (status='dispatching' AND lease_until<=? AND attempts<4)
                ORDER BY detected_at, post_id LIMIT 1""", (now, now)).fetchone()
            if row is None:
                return None
            self.db.execute("UPDATE posts SET status='dispatching', attempts=attempts+1, lease_until=? WHERE source=? AND post_id=?",
                            (now + lease_seconds, row["source"], row["post_id"]))
            return {key: row[key] for key in ("source", "post_id", "member_id")}

    def complete(self, event, now):
        with self.db:
            self.db.execute("UPDATE posts SET status='dispatched', dispatched_at=?, lease_until=0 WHERE source=? AND post_id=?",
                            (now, event["source"], event["post_id"]))
            self.heartbeat("dispatch", now)

    def fail(self, event, now, *, retry_after=0):
        with self.db:
            row = self.db.execute("SELECT attempts FROM posts WHERE source=? AND post_id=?",
                                  (event["source"], event["post_id"])).fetchone()
            attempts = row["attempts"]
            terminal = attempts >= 4
            delay = max(RETRY_DELAYS[min(attempts - 1, 2)], retry_after)
            self.db.execute("UPDATE posts SET status=?,next_attempt=?,lease_until=0 WHERE source=? AND post_id=?",
                            ("manual_review" if terminal else "failed", now + delay, event["source"], event["post_id"]))

    def scan_time(self, member_id):
        row = self.db.execute("SELECT completed_at FROM scans WHERE member_id=?", (member_id,)).fetchone()
        return row[0] if row else None

    def requeue(self, post_id, now):
        with self.db:
            result = self.db.execute("""UPDATE posts SET status='pending',attempts=0,next_attempt=?,lease_until=0
                WHERE source='x' AND post_id=? AND status IN ('failed','manual_review')""", (now, post_id))
            if result.rowcount != 1:
                raise ValueError("只允許人工重送 failed 或 manual_review 貼文")

    def scanned(self, member_id, now):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO scans VALUES(?,?)", (member_id, now))
            self.heartbeat("reconcile", now)

    def heartbeat(self, name, now):
        self.db.execute("INSERT OR REPLACE INTO health VALUES(?,?)", (name, now))
        self.db.commit()

    def report(self):
        return {"counts": dict(self.db.execute("SELECT status,COUNT(*) FROM posts GROUP BY status").fetchall()),
                "oldest_pending": self.db.execute("SELECT MIN(detected_at) FROM posts WHERE status IN ('pending','failed','dispatching')").fetchone()[0],
                "heartbeats": dict(self.db.execute("SELECT name,updated_at FROM health").fetchall()),
                "scans": dict(self.db.execute("SELECT member_id,completed_at FROM scans").fetchall())}
