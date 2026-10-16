"""以手動提供的結構化結果產生審核提案，尚未呼叫 X 或 AI。"""

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from processor.merge import merge_changes
from processor.schemas import ValidationError, load_json, validate_schema
from processor.validate import validate_data

ROOT = Path(__file__).resolve().parents[1]


def process_fixture(fixture, data_dir, timestamp):
    members, schedule, posts, revisions = [load_json(data_dir / f"{name}.json") for name in ("members", "schedule", "posts", "revisions")]
    validate_data(members, schedule, posts, revisions)
    post = fixture["post"]
    proposal = fixture["proposal"]
    if any(item["source"] == post["source"] and item["post_id"] == post["post_id"] for item in posts):
        raise ValidationError("貼文已記錄，請先確認是否需要人工重處理")
    result = merge_changes(schedule, proposal, members, source_post_id=post["post_id"],
                           member_id=post["member_id"], timestamp=timestamp)
    status = {"review": "pending_review", "record_only": "manual_review", "ignored": "ignored"}[result.decision]
    record = {**post, "processed_at": timestamp, "type": proposal["classification"], "status": status}
    validate_schema([record], "posts")
    candidate_posts = posts + [record]
    candidate_revisions = revisions + result.revisions
    validate_data(members, result.schedule, candidate_posts, candidate_revisions)
    return {"decision": result.decision, "reason": proposal["reason"], "proposal": proposal, "members": members,
            "schedule": result.schedule, "posts": candidate_posts, "revisions": candidate_revisions}


def main():
    parser = argparse.ArgumentParser(description="將手動解析結果轉為審核提案；不寫入正式 data")
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path, default=ROOT / ".local" / "proposal.json")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(ROOT / "data") or output.is_relative_to(args.data_dir.resolve()):
        parser.error("提案輸出不得位於 data 目錄")
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fixture = load_json(args.fixture)
    candidate = process_fixture(fixture, args.data_dir, timestamp)
    output.parent.mkdir(parents=True, exist_ok=True)
    # 驗證完成後才原子替換單一提案檔，避免中途失敗產生半份 JSON。
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(candidate, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    print(json.dumps({"timestamp": timestamp, "post_id": fixture["post"]["post_id"],
                      "member_id": fixture["post"]["member_id"], "classification": fixture["proposal"]["classification"],
                      "confidence": fixture["proposal"]["confidence"],
                      "operation": [change["operation"] for change in fixture["proposal"]["changes"]],
                      "result": candidate["decision"], "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
