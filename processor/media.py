import base64
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from collector.http import NoRedirect, ServiceError
from processor.manual import MAX_IMAGE_BYTES, MAX_TOTAL_IMAGE_BYTES


def download_images(images, *, timeout=30):
    prepared = []
    total = 0
    for location in images:
        parsed = urlsplit(location)
        if parsed.scheme != "https" or parsed.hostname != "pbs.twimg.com" or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ServiceError("不允許的 X 圖片來源")
        try:
            with build_opener(NoRedirect()).open(Request(location), timeout=timeout) as response:
                body = response.read(MAX_IMAGE_BYTES + 1)
        except Exception:
            raise ServiceError("圖片下載") from None
        total += len(body)
        if not body or len(body) > MAX_IMAGE_BYTES or total > MAX_TOTAL_IMAGE_BYTES:
            raise ServiceError("圖片大小")
        if body.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif body.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif body.startswith(b"RIFF") and body[8:12] == b"WEBP":
            mime = "image/webp"
        else:
            raise ServiceError("圖片格式")
        prepared.append(f"data:{mime};base64,{base64.b64encode(body).decode('ascii')}")
    return prepared
