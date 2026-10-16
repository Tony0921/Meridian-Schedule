import argparse
from pathlib import Path

from processor.schemas import load_json
from processor.validate import validate_data

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="驗證資料 Schema 與跨檔關聯")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    values = [load_json(args.data_dir / f"{name}.json") for name in ("members", "schedule", "posts", "revisions")]
    validate_data(*values)
    print(f"資料驗證通過：{len(values[0])} 位成員、{len(values[1]['events'])} 筆行程")


if __name__ == "__main__":
    main()
