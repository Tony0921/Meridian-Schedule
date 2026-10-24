"""受限主機的 HTTP 呼叫；錯誤不包含憑證或服務回應本文。"""

import json
import math
import time
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class ServiceError(ValueError):
    def __init__(self, service, *, status=None, retry_after=0):
        super().__init__(f"{service} 連線或回應失敗" + (f" (HTTP {status})" if status else ""))
        self.status = status
        self.retry_after = retry_after


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def retry_delay(headers, now=None):
    now = time.time() if now is None else now
    headers = headers or {}
    retry = headers.get("Retry-After", "0")
    try:
        delay = int(retry) if retry.isdigit() else parsedate_to_datetime(retry).timestamp() - now
    except (ValueError, TypeError, OverflowError):
        delay = 0
    try:
        reset = float(headers.get("x-rate-limit-reset", 0)) - now
    except (ValueError, TypeError):
        reset = 0
    return max(0, min(86400, math.ceil(max(delay, reset)))) if math.isfinite(max(delay, reset)) else 0


class JsonClient:
    def __init__(self, base_url, token, *, timeout=30):
        if not token or any(character.isspace() for character in token):
            raise ValueError("請設定服務 Token")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout 必須是有限正數")
        self.base_url, self._token, self.timeout = base_url, token, timeout

    def request(self, path, *, method="GET", payload=None):
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("不允許的 API 路徑")
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json",
                   "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"}
        request = Request(self.base_url + path, method=method, headers=headers,
                          data=None if payload is None else json.dumps(payload, allow_nan=False).encode())
        try:
            with build_opener(NoRedirect()).open(request, timeout=self.timeout) as response:
                body = response.read(8 * 1024 * 1024 + 1)
        except HTTPError as error:
            delay = retry_delay(error.headers)
            status = error.code
            error.close()
            raise ServiceError("API", status=status, retry_after=delay) from None
        except (TimeoutError, URLError, OSError, HTTPException):
            raise ServiceError("API") from None
        if len(body) > 8 * 1024 * 1024:
            raise ServiceError("API 回應過大")
        try:
            return json.loads(body) if body else None
        except (ValueError, UnicodeError):
            raise ServiceError("API JSON") from None
