"""將手動文字與圖片轉成與 Provider 無關的輸入，不修改正式資料。"""

import base64
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

from processor.schemas import ValidationError

MAX_IMAGES = 8
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 20 * 1024 * 1024


def validate_manual_input(manual):
    if not isinstance(manual, dict) or set(manual) - {"post", "post_text", "images"} or "post" not in manual:
        raise ValidationError("手動輸入只接受 post、post_text、images，且必須提供 post")
    text = manual.get("post_text", "")
    images = manual.get("images", [])
    if not isinstance(text, str) or not isinstance(images, list) or any(
        not isinstance(item, str) or not item.strip() for item in images
    ):
        raise ValidationError("post_text 必須是字串，images 必須是非空字串陣列")


def prepare_manual_input(manual, member, base_dir):
    post = deepcopy(manual["post"])
    text = manual.get("post_text", "")
    locations = list(dict.fromkeys([item["url"] for item in post["media"]] + manual.get("images", [])))
    if not text.strip() and not locations:
        raise ValidationError("至少提供貼文文字或一張圖片")
    if len(locations) > MAX_IMAGES:
        raise ValidationError(f"最多接受 {MAX_IMAGES} 張圖片")
    images = []
    total_bytes = 0
    for location in locations:
        parsed = urlsplit(location)
        if parsed.scheme.lower() in {"http", "https"}:
            if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password or any(
                character.isspace() for character in location
            ):
                raise ValidationError("圖片網址必須是沒有帳密的 HTTPS URL")
            images.append(location)
            if not any(item["url"] == location for item in post["media"]):
                post["media"].append({"type": "image", "url": location})
            continue
        # 本機圖片由使用者指定；只傳送內容，不把檔案路徑寫入提案或送給 AI。
        path = Path(location)
        if not path.is_absolute():
            path = base_dir / path
        with path.open("rb") as stream:
            content = stream.read(MAX_IMAGE_BYTES + 1)
        total_bytes += len(content)
        if not content or len(content) > MAX_IMAGE_BYTES or total_bytes > MAX_TOTAL_IMAGE_BYTES:
            raise ValidationError("本機圖片必須非空、每張最多 10 MiB，合計最多 20 MiB")
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif content.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
            mime = "image/webp"
        else:
            raise ValidationError("本機圖片僅接受 PNG、JPEG、WebP")
        images.append(f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}")
    return post, {"member": deepcopy(member), "post_text": text,
                  "published_at": post["published_at"], "images": images}
