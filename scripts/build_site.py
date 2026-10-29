import argparse
from pathlib import Path
from shutil import copy2

from processor.storage import atomic_json, read_data

ROOT = Path(__file__).resolve().parents[1]


def build_site(output):
    output = output.resolve()
    # 禁止把建置產物寫回原始碼或資料目錄。
    if output == ROOT or ROOT.is_relative_to(output) or any(
        output == ROOT / name or output.is_relative_to(ROOT / name)
        for name in ("site", "data", "processor", "collector", "scripts", "tests", "schemas", ".github")
    ):
        raise ValueError("請使用獨立的建置目錄，例如 dist")
    values = read_data(ROOT / "data")
    output.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "app.js", "theme.js", "style.css"):
        copy2(ROOT / "site" / name, output / name)
    (output / "data").mkdir(exist_ok=True)
    source_urls = {post["post_id"]: post["source_url"] for post in values["posts"]}
    public_schedule = {**values["schedule"], "sources": {
        event["source_post_id"]: source_urls[event["source_post_id"]]
        for event in values["schedule"]["events"]
    }}
    for name in ("members", "schedule"):
        atomic_json(public_schedule if name == "schedule" else values[name], output / "data" / f"{name}.json")
    (output / ".nojekyll").touch()
    print(f"靜態網站建置完成：{output}")


def main():
    parser = argparse.ArgumentParser(description="驗證資料並建置 GitHub Pages 靜態檔案")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    build_site(args.output)


if __name__ == "__main__":
    main()
