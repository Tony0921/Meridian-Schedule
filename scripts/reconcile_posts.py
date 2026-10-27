"""公開來源補漏只輸出 missing-post queue，待外部 AI 或人工擷取，不呼叫 AI API。"""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

from collector.sources import create_source
from ingestion.dedupe import IngestionStore
from ingestion.importer import now_iso
from ingestion.normalize import canonical_url
from processor.schemas import ValidationError, load_json, validate_schema
from processor.storage import atomic_json, data_lock, read_data
from scripts.process_post import ROOT


def reconcile_posts(source, data_dir, output, *, timestamp=None, lookback_hours=72, ingestion_db=None):
    timestamp = timestamp or now_iso()
    now = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    output, data_dir = Path(output).resolve(), Path(data_dir).resolve()
    if lookback_hours <= 0 or output.is_relative_to(data_dir) or output.is_relative_to(ROOT / "data"):
        raise ValidationError("補漏設定或輸出位置無效")
    values = read_data(data_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    with data_lock(output.parent):
        state = load_json(output) if output.exists() else {"posts": [], "scans": {}}
        seen = {(post["source"], post["post_id"]) for post in values["posts"]}
        seen.update((item["post"]["source"], item["post"]["post_id"]) for item in state["posts"])
        urls = {canonical_url(post["source_url"]) for post in values["posts"]}
        urls.update(canonical_url(item["post"]["source_url"]) for item in state["posts"])
        failures = []
        store = IngestionStore(ingestion_db) if ingestion_db and Path(ingestion_db).is_file() else None
        try:
            for member in values["members"]:
                if not member["enabled"] or not member["x_username"]:
                    continue
                previous = state["scans"].get(member["id"])
                since = max(now - timedelta(hours=lookback_hours),
                            datetime.fromisoformat(previous.replace("Z", "+00:00")) - timedelta(hours=1) if previous else now - timedelta(hours=lookback_hours))
                try:
                    pending = []
                    for event in source.fetch_recent(member, since.isoformat(timespec="seconds")):
                        if event["member_id"] != member["id"]:
                            raise ValidationError("來源成員不一致")
                        manual = source.fetch_post(event["post_id"])
                        post = manual["post"]
                        validate_schema([{**post, "processed_at": timestamp, "type": "unknown", "status": "manual_review"}], "posts")
                        if any(post[key] != event[key] for key in ("source", "post_id", "member_id")):
                            raise ValidationError("來源貼文不一致")
                        identity = (post["source"], post["post_id"])
                        if identity in seen or canonical_url(post["source_url"]) in urls or (store and store.duplicate(post)):
                            continue
                        pending.append({"post": post, "post_text": manual.get("post_text", ""), "images": manual.get("images", []),
                                        "discovery_source": "x_public", "source_quality": "secondary", "discovered_at": timestamp})
                    for manual in pending:
                        post = manual["post"]
                        identity = (post["source"], post["post_id"])
                        if identity not in seen:
                            state["posts"].append(manual)
                            seen.add(identity)
                            urls.add(canonical_url(post["source_url"]))
                    state["scans"][member["id"]] = timestamp
                except Exception as error:
                    failures.append({"member_id": member["id"], "error": type(error).__name__})
            state["last_run"] = timestamp
            state["failures"] = failures
            atomic_json(state, output)
        finally:
            if store:
                store.close()
    return {"result": "failed" if failures else "ok", "missing_posts": len(state["posts"]), "failures": failures}


def main(argv=None):
    parser = argparse.ArgumentParser(description="免費公開來源補漏；不推測未發現貼文代表取消或休息")
    parser.add_argument("--source", default="collector.x_public:create")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path, default=ROOT / ".local/reconciliation/missing-posts.json")
    parser.add_argument("--ingestion-db", type=Path, default=ROOT / ".local/ingestion/ingestion.db")
    parser.add_argument("--lookback-hours", type=int, default=72)
    args = parser.parse_args(argv)
    try:
        members = read_data(args.data_dir)["members"]
        source = create_source(args.source, members)
        result = reconcile_posts(source, args.data_dir, args.output, lookback_hours=args.lookback_hours, ingestion_db=args.ingestion_db)
        print(json.dumps(result))
        return int(result["result"] == "failed")
    except Exception as error:
        print(json.dumps({"result": "failed", "error": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
