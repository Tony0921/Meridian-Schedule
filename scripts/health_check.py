import argparse
import json
import time
from pathlib import Path

from collector.dedupe import PostStore
from processor.storage import read_data
from scripts.process_post import ROOT


def main(argv=None):
    parser = argparse.ArgumentParser(description="資料、Collector 心跳與待人工處理項目檢查")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--db", type=Path)
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
    except (ValueError, OSError, KeyError, TypeError):
        issues.append("invalid_data_or_state")
    print(json.dumps({"result": "unhealthy" if issues else "healthy", "issues": issues, **details}))
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
