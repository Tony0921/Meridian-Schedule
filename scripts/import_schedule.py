"""從公開 CSV 或本機 CSV 匯入行程；不使用 Google／X／AI API。"""

import argparse
import json
import logging
import os
from pathlib import Path

from ingestion.schedule_csv import MAX_CSV_BYTES, download_csv, import_schedule

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description="V2.3 schedule_ingestion CSV 匯入")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--input", type=Path, help="本機 UTF-8 CSV")
    source.add_argument("--url", help="Publish to Web CSV URL；預設讀 SCHEDULE_CSV_URL")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--backup-dir", type=Path, default=ROOT / ".local/backups")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    try:
        if args.input:
            with args.input.open("rb") as stream:
                body = stream.read(MAX_CSV_BYTES + 1)
            if len(body) > MAX_CSV_BYTES:
                raise ValueError("CSV 過大")
            text = body.decode("utf-8-sig")
        else:
            url = args.url or os.environ.get("SCHEDULE_CSV_URL")
            if not url:
                raise ValueError("缺少 SCHEDULE_CSV_URL 或 --input")
            text = download_csv(url)
        result = import_schedule(text, args.data_dir, args.backup_dir)
    except (ValueError, OSError, KeyError, TypeError):
        print(json.dumps({"result": "failed", "error": "CSV 無法下載、解析或寫入；請檢查設定與資料交易狀態"}, ensure_ascii=False))
        return 1
    print(json.dumps({"result": "success", **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
