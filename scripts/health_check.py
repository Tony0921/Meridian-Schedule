import argparse
import json
from pathlib import Path

from processor.storage import read_data

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description="正式資料關聯與待人工處理來源檢查")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args(argv)
    issues = []
    details = {}
    try:
        values = read_data(args.data_dir)
        details["manual_review_posts"] = sum(post["status"] in {"manual_review", "failed"} for post in values["posts"])
        if details["manual_review_posts"]:
            issues.append("posts_need_review")
    except (ValueError, OSError, KeyError, TypeError, AttributeError):
        issues.append("invalid_data_or_state")
    print(json.dumps({"result": "unhealthy" if issues else "healthy", "issues": issues, **details}))
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
