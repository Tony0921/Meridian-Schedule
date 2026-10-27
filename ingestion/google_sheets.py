"""Google Sheets REST adapter；憑證與 HTTP 回應本文不寫入日誌。"""

import json
import os
import re
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener
from urllib.error import HTTPError, URLError
from http.client import HTTPException

from collector.http import JsonClient, NoRedirect, ServiceError
from ingestion.models import CHANGE_COLUMNS, POST_COLUMNS, QUEUE_STATUSES, QueueSnapshot
from processor.schemas import ValidationError, load_json
from processor.storage import atomic_json


def access_token():
    if os.environ.get("GOOGLE_ACCESS_TOKEN"):
        return os.environ["GOOGLE_ACCESS_TOKEN"]
    keys = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")
    if not all(os.environ.get(key) for key in keys):
        raise ValueError("請設定 GOOGLE_ACCESS_TOKEN 或 Google OAuth refresh credentials")
    data = dict(zip(("client_id", "client_secret", "refresh_token"), (os.environ[key] for key in keys)))
    data["grant_type"] = "refresh_token"
    request = Request("https://oauth2.googleapis.com/token", data=urlencode(data).encode(),
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            body = response.read(65537)
        if len(body) > 65536:
            raise ValueError("OAuth 回應過大")
        token = json.loads(body)["access_token"]
        if not isinstance(token, str) or not token or any(char.isspace() for char in token):
            raise ValueError("OAuth Token 無效")
        return token
    except HTTPError as error:
        status = error.code
        error.close()
        raise ServiceError("Google OAuth", status=status) from None
    except (ValueError, KeyError, TypeError, URLError, OSError, HTTPException):
        raise ServiceError("Google OAuth") from None


def table_rows(values, columns):
    if not isinstance(values, list) or not values or not isinstance(values[0], list):
        raise ValidationError("Sheet 缺少標題列")
    headers = values[0]
    if any(not isinstance(value, str) for value in headers) or len(headers) != len(set(headers)):
        raise ValidationError("Sheet 標題重複或無效")
    # 只允許選配的來源品質欄位省略，避免寫回錯誤欄位或讀到不完整 operation。
    required = set(columns) - {"discovery_source", "source_quality"}
    if not required <= set(headers) or set(headers) - set(columns):
        raise ValidationError("Sheet 欄位與 schema 不符")
    rows = []
    for values_row in values[1:]:
        if not isinstance(values_row, list) or len(values_row) > len(headers):
            raise ValidationError("Sheet 資料列格式錯誤")
        if any(value not in (None, "") for value in values_row):
            rows.append(dict(zip(headers, values_row + [""] * (len(headers) - len(values_row)))))
    return headers, rows


class GoogleSheetsObservationSource(JsonClient):
    def __init__(self, sheet_id, token, *, timeout=30):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", sheet_id or ""):
            raise ValueError("GOOGLE_SHEET_ID 格式不符")
        super().__init__("https://sheets.googleapis.com", token, timeout=timeout)
        self.path = "/v4/spreadsheets/" + sheet_id + "/values"

    def _table(self, name, columns):
        result = self.request(self.path + "/" + quote(name + "!A:Z", safe="") + "?valueRenderOption=UNFORMATTED_VALUE")
        return table_rows(result.get("values", []), columns)

    def read(self):
        _, posts = self._table("posts", POST_COLUMNS)
        _, changes = self._table("changes", CHANGE_COLUMNS)
        return QueueSnapshot(posts, changes)

    def update(self, ingestion_id, *, status, processed_at, processor_result):
        if status not in QUEUE_STATUSES:
            raise ValueError("Queue status 無效")
        # 重讀列號，避免人工排序後將狀態寫到另一篇貼文；匯入期間仍須避免移動資料列。
        result = self.request(self.path + "/" + quote("posts!A:Z", safe="") + "?valueRenderOption=UNFORMATTED_VALUE")
        headers, _ = table_rows(result.get("values", []), POST_COLUMNS)
        id_column = headers.index("ingestion_id")
        matches = [index for index, row in enumerate(result["values"][1:], 2)
                   if len(row) > id_column and str(row[id_column]) == ingestion_id]
        if len(matches) != 1:
            raise ValidationError("ingestion_id 不存在或重複，停止狀態回寫")
        updates = {"status": status, "processed_at": processed_at, "processor_result": processor_result}
        data = [{"range": f"posts!{chr(65 + headers.index(key))}{matches[0]}", "values": [[value]]}
                for key, value in updates.items()]
        self.request(self.path + ":batchUpdate", method="POST", payload={"valueInputOption": "RAW", "data": data})


class JsonObservationSource:
    """使用相同欄位的離線 queue；只回寫指定輸入檔的狀態。"""

    def __init__(self, path):
        self.path = path

    def read(self):
        value = load_json(self.path)
        if not isinstance(value, dict) or set(value) != {"posts", "changes"}:
            raise ValidationError("離線 queue 必須包含 posts / changes")
        if any(not isinstance(value[key], list) or any(not isinstance(row, dict) for row in value[key]) for key in value):
            raise ValidationError("離線 queue 資料列格式錯誤")
        return QueueSnapshot(value["posts"], value["changes"])

    def update(self, ingestion_id, **updates):
        snapshot = self.read()
        matches = [row for row in snapshot.posts if row.get("ingestion_id") == ingestion_id]
        if len(matches) != 1:
            raise ValidationError("ingestion_id 不存在或重複")
        matches[0].update(updates)
        atomic_json({"posts": snapshot.posts, "changes": snapshot.changes}, self.path)
