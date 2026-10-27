"""匯入 Google Sheets 或離線 queue，預設只輸出待審提案。"""

import argparse
import json
import os
from pathlib import Path

from ingestion.google_sheets import GoogleSheetsObservationSource, JsonObservationSource, access_token
from ingestion.importer import import_queue
from processor.classify import ConfidencePolicy
from scripts.process_post import ROOT


def main(argv=None):
    parser = argparse.ArgumentParser(description="v2 Observation 匯入；不需要 X 或 AI API Key")
    parser.add_argument("--input", type=Path, help="離線 queue JSON；會回寫此檔狀態")
    parser.add_argument("--sheet-id", default=os.environ.get("GOOGLE_SHEET_ID"))
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--state-dir", type=Path, default=ROOT / ".local/ingestion")
    parser.add_argument("--publish", action="store_true", help="呼叫既有 GitHub 發布流程；預設建立待審 PR")
    parser.add_argument("--retry-ingestion", help="人工修正後重產指定的未發布 review / failed 提案；保留舊檔")
    args = parser.parse_args(argv)
    if args.input and (args.input.resolve().is_relative_to(args.data_dir.resolve())
                       or args.input.resolve().is_relative_to(ROOT / "data")):
        parser.error("離線 queue 不得位於 data 目錄")
    try:
        policy = ConfidencePolicy(float(os.environ.get("AUTO_MERGE_CONFIDENCE", "0.95")),
                                  float(os.environ.get("PR_CONFIDENCE", "0.70")),
                                  os.environ.get("REVIEW_ALL", "true").lower() != "false")
        source = JsonObservationSource(args.input) if args.input else GoogleSheetsObservationSource(args.sheet_id, access_token())
        publisher = None
        if args.publish:
            if args.data_dir.resolve() != ROOT / "data":
                raise ValueError("發布只允許使用 repository 的正式 data")
            from collector.github_dispatch import GitHubClient
            from scripts.publish_proposal import publish
            client = GitHubClient(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])
            publisher = lambda bundle: publish(bundle, ROOT, client, policy=policy,
                                               base=os.environ.get("SCHEDULE_BASE_BRANCH", "main"))
        results = import_queue(source, args.data_dir, args.state_dir, policy=policy, publisher=publisher, retry_ingestion=args.retry_ingestion)
        for result in results:
            print(json.dumps(result, ensure_ascii=False))
        return int(any(result["result"] == "failed" for result in results))
    except Exception as error:
        print(json.dumps({"result": "failed", "error": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
