"""將手動 AI 輸入或既有結構化 fixture 轉成審核提案，不修改正式資料。"""

import argparse
import json
import os
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from processor.extract import InterpreterError, ScheduleInterpreter, create_interpreter
from processor.manual import prepare_manual_input, validate_manual_input
from processor.merge import merge_changes
from processor.schemas import ValidationError, load_json, validate_schema
from processor.validate import validate_data

ROOT = Path(__file__).resolve().parents[1]


def _load_context(post, data_dir, timestamp):
    if not isinstance(post, dict) or set(post) != {
        "source", "post_id", "member_id", "published_at", "source_url", "media"
    }:
        raise ValidationError("post 必須且只能包含 source、post_id、member_id、published_at、source_url、media")
    validate_schema([{**post, "processed_at": timestamp, "type": "unknown", "status": "manual_review"}], "posts")
    members, schedule, posts, revisions = [load_json(data_dir / f"{name}.json") for name in ("members", "schedule", "posts", "revisions")]
    validate_data(members, schedule, posts, revisions)
    if any(item["source"] == post["source"] and item["post_id"] == post["post_id"] for item in posts):
        raise ValidationError("貼文已記錄，請先確認是否需要人工重處理")
    if post["member_id"] not in {member["id"] for member in members if member["enabled"]}:
        raise ValidationError("來源成員不存在或未啟用")
    return members, schedule, posts, revisions


def _build_proposal(post, proposal, context, timestamp):
    members, schedule, posts, revisions = context
    validate_schema(proposal, "changes")
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


def process_fixture(fixture, data_dir, timestamp):
    post = fixture["post"]
    return _build_proposal(post, fixture["proposal"], _load_context(post, data_dir, timestamp), timestamp)


def process_manual_post(manual, data_dir, timestamp, interpreter: ScheduleInterpreter, *, base_dir):
    validate_manual_input(manual)
    context = _load_context(manual["post"], data_dir, timestamp)
    members, schedule, _, _ = context
    member = next(item for item in members if item["id"] == manual["post"]["member_id"])
    post, interpreter_input = prepare_manual_input(manual, member, base_dir)
    member_schedule = {"updated_at": schedule["updated_at"],
                       "events": deepcopy([event for event in schedule["events"] if event["member_id"] == member["id"]])}
    proposal = interpreter.extract(interpreter_input, member_schedule)
    return _build_proposal(post, proposal, context, timestamp)


def write_proposal(candidate, output):
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


def main(argv=None):
    parser = argparse.ArgumentParser(description="將手動 AI 輸入或解析結果轉為審核提案；不寫入正式 data")
    parser.add_argument("fixture", type=Path, nargs="?", help="既有結構化 fixture（不呼叫 AI）")
    parser.add_argument("--manual", type=Path, help="包含 post、post_text、images 的手動輸入 JSON")
    parser.add_argument("--provider", default="openai", help="openai 或 module:factory")
    parser.add_argument("--model", help="模型名稱；OpenAI 預設讀取 OPENAI_MODEL")
    parser.add_argument("--timeout", type=float, default=60, help="AI API 逾時秒數，預設 60")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path, default=ROOT / ".local" / "proposal.json")
    args = parser.parse_args(argv)
    if (args.fixture is None) == (args.manual is None):
        parser.error("請選擇 fixture 或 --manual，兩者不可同時使用")
    input_path = (args.manual or args.fixture).resolve()
    output = args.output.resolve()
    if output.is_relative_to(ROOT / "data") or output.is_relative_to(args.data_dir.resolve()) or output == input_path:
        parser.error("提案輸出不得位於 data 目錄或覆蓋輸入檔")
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        value = load_json(input_path)
        if args.manual:
            interpreter = create_interpreter(args.provider, model=args.model, timeout=args.timeout)
            candidate = process_manual_post(value, args.data_dir, timestamp, interpreter, base_dir=input_path.parent)
        else:
            candidate = process_fixture(value, args.data_dir, timestamp)
        write_proposal(candidate, output)
    except (InterpreterError, ValidationError, OSError, ValueError, KeyError) as error:
        print(json.dumps({"timestamp": timestamp, "result": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    proposal = candidate["proposal"]
    post = value["post"]
    print(json.dumps({"timestamp": timestamp, "post_id": post["post_id"],
                      "member_id": post["member_id"], "classification": proposal["classification"],
                      "confidence": proposal["confidence"], "operation": [change["operation"] for change in proposal["changes"]],
                      "result": candidate["decision"], "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
