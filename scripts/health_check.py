import argparse
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from collector.dedupe import PostStore
from ingestion.dedupe import IngestionStore
from processor.schemas import load_json
from processor.storage import read_data
from scripts.process_post import ROOT


def main(argv=None):
    parser = argparse.ArgumentParser(description="資料、Collector 心跳與待人工處理項目檢查")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--ingestion-db", type=Path)
    parser.add_argument("--reconciliation", type=Path)
    parser.add_argument("--max-heartbeat-age", type=int, default=300)
    args = parser.parse_args(argv)
    if args.max_heartbeat_age <= 0:
        parser.error("max-heartbeat-age 必須為正數")
    issues = []
    details = {}
    try:
        values = read_data(args.data_dir)
        details["manual_review_posts"] = sum(post["status"] in {"manual_review", "failed"} for post in values["posts"])
        if details["manual_review_posts"]:
            issues.append("posts_need_review")
        if args.ingestion_db:
            if not args.ingestion_db.is_file():
                raise ValueError("Ingestion DB 不存在")
            ingestion = IngestionStore(args.ingestion_db)
            try:
                details["ingestion"] = report = ingestion.report()
            finally:
                ingestion.close()
            def age(stamp):
                return time.time() - datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() if stamp else float("inf")
            if age(report.get("last_sheet_read")) > 86400:
                issues.append("google_sheets_stale")
            if report.get("queue_counts", {}).get("failed", 0) or report.get("local_counts", {}).get("failed", 0):
                issues.append("ingestion_failed")
            if any(age(stamp) > 3600 for stamp in report.get("processing_since", []) + report.get("local_processing_since", [])):
                issues.append("ingestion_stuck")
        if args.reconciliation:
            state = load_json(args.reconciliation)
            details["reconciliation"] = {key: state.get(key) for key in ("last_run", "scans", "failures")}
            if state.get("failures"):
                issues.append("public_reconcile_failed")
            for member in values["members"]:
                if not member["enabled"] or not member["x_username"]:
                    continue
                stamp = state.get("scans", {}).get(member["id"])
                if not stamp or time.time() - datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() > 14 * 3600:
                    issues.append("public_reconcile_stale:" + member["id"])
        if args.db:
            if not args.db.is_file():
                raise ValueError("Collector DB 不存在")
            store = PostStore(args.db)
            try:
                details["collector"] = report = store.report()
            finally:
                store.close()
            now = time.time()
            for name in ("collector", "source"):
                if now - report["heartbeats"].get(name, 0) > args.max_heartbeat_age:
                    issues.append(name + "_stale")
            if report["counts"].get("manual_review", 0):
                issues.append("dispatch_needs_review")
            if report["oldest_pending"] is not None and now - report["oldest_pending"] > 3600:
                issues.append("dispatch_backlog")
            for member in values["members"]:
                if member["enabled"] and member["x_username"] and now - report["scans"].get(member["id"], 0) > 14 * 3600:
                    issues.append("reconcile_stale:" + member["id"])
    except (ValueError, OSError, KeyError, TypeError, AttributeError, sqlite3.Error):
        issues.append("invalid_data_or_state")
    print(json.dumps({"result": "unhealthy" if issues else "healthy", "issues": issues, **details}))
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
