"""由來源取得完整貼文並沿用手動 Parser；失敗狀態保存在 workflow artifact。"""

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from collector.events import validate_event
from collector.sources import create_source
from processor.classify import ConfidencePolicy
from processor.extract import create_interpreter
from processor.storage import atomic_json, read_data
from scripts.process_post import ROOT, process_manual_post, write_proposal


def process_event(event, data_dir, output_dir, source, interpreter, *, policy=None, delays=(60, 300, 1800),
                  sleep=time.sleep, download_media=False):
    event = validate_event(event)
    output_dir = Path(output_dir)
    for attempt in range(len(delays) + 1):
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        log = {"timestamp": stamp, **event, "classification": None, "confidence": None,
               "operation": [], "attempt": attempt + 1}
        try:
            values = read_data(data_dir)
            if any((post["source"], post["post_id"]) == (event["source"], event["post_id"]) for post in values["posts"]):
                log["result"] = "duplicate"
                atomic_json(log, output_dir / "status.json")
                print(json.dumps(log))
                return None
            if event["member_id"] not in {member["id"] for member in values["members"] if member["enabled"]}:
                raise ValueError("來源成員不存在或未啟用")
            manual = source.fetch_post(event["post_id"])
            if {key: manual["post"][key] for key in event} != event:
                raise ValueError("取得的貼文與通知不一致")
            atomic_json(manual, output_dir / "source.json")
            candidate = process_manual_post(manual, Path(data_dir), stamp, interpreter, base_dir=output_dir,
                                            policy=policy, download_media=download_media)
            write_proposal(candidate, output_dir / "proposal.json")
            proposal = candidate["proposal"]
            log.update(classification=proposal["classification"], confidence=proposal["confidence"],
                       operation=[change["operation"] for change in proposal["changes"]], result=candidate["decision"])
            atomic_json(log, output_dir / "status.json")
            print(json.dumps(log))
            return candidate
        except Exception as error:
            log.update(result="manual_review" if attempt == len(delays) else "failed", error=type(error).__name__)
            atomic_json(log, output_dir / "status.json")
            print(json.dumps(log))
            if attempt == len(delays):
                raise ValueError("處理失敗且已達重試上限，請檢查 artifact") from None
            sleep(max(delays[attempt], getattr(error, "retry_after", 0)))


def main(argv=None):
    parser = argparse.ArgumentParser(description="處理外部貼文通知；不直接寫入正式資料")
    parser.add_argument("--event", type=Path, default=Path(os.environ.get("GITHUB_EVENT_PATH", ".local/event.json")))
    parser.add_argument("--source", default=os.environ.get("POST_SOURCE", "x-api"))
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".local/event")
    parser.add_argument("--no-retry", action="store_true")
    args = parser.parse_args(argv)
    event = {}
    output_valid = False
    try:
        if args.output_dir.resolve().is_relative_to(args.data_dir.resolve()):
            raise ValueError("輸出不可位於資料目錄")
        output_valid = True
        raw = json.loads(args.event.read_text(encoding="utf-8"))
        event = validate_event(raw.get("client_payload", raw.get("inputs", raw)))
        members = read_data(args.data_dir)["members"]
        source = create_source(args.source, members)
        policy = ConfidencePolicy(float(os.environ.get("AUTO_MERGE_CONFIDENCE", "0.95")),
                                  float(os.environ.get("PR_CONFIDENCE", "0.70")),
                                  os.environ.get("REVIEW_ALL", "true").lower() != "false")
        candidate = process_event(event, args.data_dir, args.output_dir, source, create_interpreter(), policy=policy,
                                  delays=() if args.no_retry else (60, 300, 1800), download_media=args.source == "x-api")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
                stream.write("candidate=" + ("true" if candidate is not None else "false") + "\n")
        return 0
    except Exception as error:
        status = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), **event,
                  "classification": None, "confidence": None, "operation": [],
                  "result": "failed", "error": type(error).__name__}
        if output_valid and not (args.output_dir / "status.json").exists():
            atomic_json(status, args.output_dir / "status.json")
        print(json.dumps(status))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
