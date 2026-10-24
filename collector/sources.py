"""可替換來源：JSONL 用於離線重播，X API 用於已取得存取權的帳號。"""

import json
import os
import re
from datetime import datetime
from importlib import import_module
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, build_opener
from urllib.error import HTTPError, URLError
from http.client import HTTPException

from collector.events import validate_event
from collector.http import JsonClient, NoRedirect, ServiceError, retry_delay

FIELDS = {"tweet.fields": "created_at,author_id,attachments", "expansions": "author_id,attachments.media_keys",
          "user.fields": "username", "media.fields": "url,type"}


class JsonlSource:
    def __init__(self, path):
        self.path = Path(path)

    def listen(self):
        with self.path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    manual = json.loads(line)
                    yield validate_event({key: manual["post"][key] for key in ("source", "post_id", "member_id")})
                except (ValueError, KeyError, TypeError):
                    continue

    def fetch_post(self, post_id):
        with self.path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    manual = json.loads(line)
                    if manual["post"]["post_id"] == post_id:
                        return manual
                except (ValueError, KeyError, TypeError):
                    continue
        raise ServiceError("貼文不存在")

    def fetch_recent(self, account, since):
        for event in self.listen():
            if event["member_id"] == account["id"]:
                manual = self.fetch_post(event["post_id"])
                if datetime.fromisoformat(manual["post"]["published_at"].replace("Z", "+00:00")) >= datetime.fromisoformat(since.replace("Z", "+00:00")):
                    yield event


class XAPISource(JsonClient):
    def __init__(self, members, token, *, timeout=30):
        super().__init__("https://api.x.com", token, timeout=timeout)
        self.members = {member["x_username"].casefold(): member for member in members
                        if member["enabled"] and member["x_username"]}
        self.users = {}

    def _manual(self, data, envelope):
        users = {user["id"]: user["username"] for user in envelope.get("includes", {}).get("users", [])}
        username = users.get(data["author_id"], self.users.get(data["author_id"], ""))
        member = self.members.get(username.casefold())
        if member is None:
            raise ServiceError("貼文作者不在啟用名單")
        media = {item["media_key"]: item for item in envelope.get("includes", {}).get("media", [])}
        images = []
        for key in data.get("attachments", {}).get("media_keys", []):
            item = media.get(key)
            if item is None:
                raise ServiceError("貼文媒體資料不完整")
            if item["type"] == "photo":
                if not item.get("url"):
                    raise ServiceError("圖片網址缺失")
                images.append({"type": "image", "url": item["url"]})
        return {"post": {"source": "x", "post_id": data["id"], "member_id": member["id"],
                         "published_at": data["created_at"], "source_url": f"https://x.com/{username}/status/{data['id']}",
                         "media": images}, "post_text": data["text"], "images": []}

    def fetch_post(self, post_id):
        if not re.fullmatch(r"\d{1,30}", post_id):
            raise ValueError("X post_id 必須是數字")
        result = self.request("/2/tweets/" + post_id + "?" + urlencode(FIELDS))
        try:
            return self._manual(result["data"], result)
        except (KeyError, TypeError):
            raise ServiceError("X 貼文資料不完整") from None

    def fetch_recent(self, account, since):
        username = account["x_username"]
        if username is None:
            return
        if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,15}", username):
            raise ValueError("X username 格式不正確")
        user = self.request("/2/users/by/username/" + username)["data"]
        self.users[user["id"]] = username
        token = None
        seen = set()
        while True:
            params = {**FIELDS, "start_time": since, "max_results": 100, "exclude": "retweets"}
            if token:
                params["pagination_token"] = token
            result = self.request("/2/users/" + user["id"] + "/tweets?" + urlencode(params))
            if result.get("errors"):
                raise ServiceError("X 近期貼文不完整")
            for data in result.get("data", []):
                yield {"source": "x", "post_id": data["id"], "member_id": account["id"]}
            token = result.get("meta", {}).get("next_token")
            if not token:
                break
            if token in seen:
                raise ServiceError("X 分頁重複")
            seen.add(token)

    def setup_rules(self):
        existing = self.request("/2/tweets/search/stream/rules")
        values = {rule["value"] for rule in (existing or {}).get("data", [])}
        rules = [{"value": f"from:{username} -is:retweet", "tag": "meridian-schedule"}
                 for username in self.members if f"from:{username} -is:retweet" not in values]
        if rules:
            result = self.request("/2/tweets/search/stream/rules", method="POST", payload={"add": rules})
            if result.get("errors"):
                raise ServiceError("X 規則設定")

    def listen(self):
        request = Request(self.base_url + "/2/tweets/search/stream?" + urlencode(FIELDS),
                          headers={"Authorization": f"Bearer {self._token}"})
        try:
            with build_opener(NoRedirect()).open(request, timeout=self.timeout) as response:
                while True:
                    line = response.readline(1024 * 1024 + 1)
                    if not line:
                        return
                    if len(line) > 1024 * 1024:
                        raise ServiceError("X 串流資料過大")
                    if not line.strip():
                        yield None
                        continue
                    try:
                        result = json.loads(line)
                        manual = self._manual(result["data"], result)
                        yield validate_event({key: manual["post"][key] for key in ("source", "post_id", "member_id")})
                    except (ValueError, KeyError, TypeError):
                        # 不相關作者或單篇毀損不終止持續接收。
                        continue
        except HTTPError as error:
            status = error.code
            delay = retry_delay(error.headers)
            error.close()
            raise ServiceError("X 串流", status=status, retry_after=max(delay, 60 if status == 429 else 0)) from None
        except (TimeoutError, URLError, OSError, HTTPException):
            raise ServiceError("X 串流") from None


def create_source(name, members, *, timeout=30):
    if name == "x-api":
        return XAPISource(members, os.environ.get("X_API_TOKEN"), timeout=timeout)
    if name == "jsonl":
        return JsonlSource(os.environ["POSTS_JSONL"])
    module, factory = name.split(":")
    return getattr(import_module(module), factory)(members=members, timeout=timeout)
