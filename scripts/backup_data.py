import argparse
import json
from pathlib import Path

from processor.storage import data_lock, load_snapshot, recover_unlocked, snapshot, write_data_unlocked

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description="資料備份、復原及中斷交易復原")
    parser.add_argument("action", choices=("backup", "restore", "recover"))
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--backup-dir", type=Path, default=ROOT / ".local/backups")
    args = parser.parse_args(argv)
    if args.action == "restore" and args.snapshot is None:
        parser.error("restore 必須指定 --snapshot")
    try:
        with data_lock(args.data_dir):
            if args.action == "backup":
                result = str(snapshot(args.data_dir, args.backup_dir))
            elif args.action == "recover":
                result = recover_unlocked(args.data_dir)
            else:
                restored = load_snapshot(args.snapshot)["data"]
                # 舊版備份沒有 receipt；還原時清空，避免行程退回後仍略過已撤回的匯入。
                restored.setdefault("imported_ids", [])
                result = str(write_data_unlocked(args.data_dir, restored, args.backup_dir))
        print(json.dumps({"result": "success", "action": args.action, "backup": result}))
        return 0
    except (ValueError, OSError, KeyError, TypeError):
        print(json.dumps({"result": "failed", "action": args.action}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
