"""明確採用已審核提案；不信任候選資料，重新執行 merge。"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from processor.classify import ConfidencePolicy
from processor.schemas import ValidationError, load_json, validate_schema
from processor.storage import NAMES, data_lock, fingerprint, read_unlocked, write_data_unlocked
from scripts.process_post import ROOT, _build_proposal


def apply_proposal(bundle, directory, backup_dir, *, approve=False, policy=None, rebase=False):
    directory = Path(directory).resolve()
    policy = policy or ConfidencePolicy()
    post = bundle["post"]
    if set(post) != {"source", "post_id", "member_id", "published_at", "source_url", "media"}:
        raise ValidationError("提案來源欄位不正確")
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    validate_schema([{**post, "processed_at": stamp, "type": "unknown", "status": "manual_review"}], "posts")
    with data_lock(directory):
        values = read_unlocked(directory)
        if not rebase and bundle.get("base_hash") != fingerprint(values):
            raise ValidationError("提案已過期，請重新解析或重新產生提案")
        if any((item["source"], item["post_id"]) == (post["source"], post["post_id"]) for item in values["posts"]):
            raise ValidationError("貼文已記錄，不可重複採用")
        candidate = _build_proposal(post, bundle["proposal"], [values[name] for name in NAMES], stamp, policy)
        if rebase and bundle.get("base_hash") != fingerprint(values):
            baseline = bundle.get("base", {})
            if fingerprint(baseline) != bundle.get("base_hash"):
                raise ValidationError("缺少可驗證的提案基準")
            expected = _build_proposal(post, bundle["proposal"], [baseline[name] for name in NAMES], stamp, policy)
            previous = {}
            for revision in expected["revisions"][len(baseline["revisions"]):]:
                if revision["before"] is not None:
                    previous.setdefault(revision["event_id"], revision["before"])
            fields = set()
            for change in bundle["proposal"]["changes"]:
                fields.update(change.get("set", {}))
                if change["operation"] == "cancel":
                    fields.add("status")
            checked = set()
            for revision in candidate["revisions"][len(values["revisions"]):]:
                before = revision["before"]
                if before is None or revision["event_id"] in checked:
                    continue
                original = previous.get(revision["event_id"])
                if original is None or any(original.get(field) != before.get(field) for field in fields):
                    raise ValidationError("提案要修改的事件欄位已異動，請重新解析")
                checked.add(revision["event_id"])
        decision = candidate["decision"]
        if decision == "review" and not approve:
            raise ValidationError("行程變更需先審核，採用時加上 --approve")
        if decision == "review":
            candidate["posts"][-1]["status"] = "processed"
        backup = write_data_unlocked(directory, candidate, backup_dir)
        return {"decision": decision, "backup": str(backup)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="驗證、備份並採用提案；低信心只記錄來源")
    parser.add_argument("proposal", type=Path)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--backup-dir", type=Path, default=ROOT / ".local/backups")
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = apply_proposal(load_json(args.proposal), args.data_dir, args.backup_dir, approve=args.approve)
    except (ValueError, OSError, KeyError, TypeError):
        print(json.dumps({"result": "failed", "error": "提案無效、已過期、尚未核准或資料正在使用"}, ensure_ascii=False))
        return 1
    print(json.dumps({"result": "applied", **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
