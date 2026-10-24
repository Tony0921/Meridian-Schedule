import argparse
from pathlib import Path

from processor.storage import read_data

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="驗證資料 Schema 與跨檔關聯")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    values = read_data(args.data_dir)
    print(f"資料驗證通過：{len(values['members'])} 位成員、{len(values['schedule']['events'])} 筆行程")


if __name__ == "__main__":
    main()
