"""可丟棄的公開 RSS adapter；Feed 僅供補漏，不視為官方行程證據。"""

import os
import json
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlsplit
from urllib.request import Request, build_opener
from urllib.error import HTTPError, URLError
from http.client import HTTPException
from xml.etree import ElementTree

from collector.http import NoRedirect, ServiceError


class XPublicSource:
    def __init__(self, members, feeds, *, timeout=30):
        self.members = members
        self.feeds = feeds
        self.timeout = timeout
        self.posts = {}

    def fetch_recent(self, account, since):
        username = account.get("x_username")
        feed = self.feeds.get(account["id"])
        if not username or not feed:
            raise ServiceError("X public feed 尚未設定")
        parts = urlsplit(feed)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError("Feed 必須是無帳密的 HTTPS URL")
        try:
            with build_opener(NoRedirect()).open(Request(feed, headers={"Accept": "application/rss+xml"}), timeout=self.timeout) as response:
                body = response.read(8 * 1024 * 1024 + 1)
            if len(body) > 8 * 1024 * 1024:
                raise ValueError("Feed 回應過大")
            root = ElementTree.fromstring(body)
            if root.tag != "rss" or root.find("channel") is None:
                raise ValueError("Feed 必須為 RSS 2.0")
            posts = []
            for item in root.findall("./channel/item"):
                link = urlsplit(item.findtext("link", ""))
                match = re.fullmatch(r"/([^/]+)/status/(\d+)/?", link.path)
                if not match or match[1].casefold() != username.casefold():
                    continue
                published = parsedate_to_datetime(item.findtext("pubDate", ""))
                if published.tzinfo is None:
                    raise ValueError("Feed 日期缺少時區")
                if published < datetime.fromisoformat(since.replace("Z", "+00:00")):
                    continue
                post_id = match[2]
                text = unescape(re.sub(r"<[^>]*>", " ", item.findtext("description") or item.findtext("title", ""))).strip()
                post = {"source": "x", "post_id": post_id, "member_id": account["id"],
                        "published_at": published.isoformat(timespec="seconds"),
                        "source_url": f"https://x.com/{username}/status/{post_id}", "media": []}
                self.posts[post_id] = {"post": post, "post_text": text, "images": [],
                                       "discovery_source": "x_public", "source_quality": "secondary"}
                posts.append({key: post[key] for key in ("source", "post_id", "member_id")})
            return posts
        except HTTPError as error:
            status = error.code
            error.close()
            raise ServiceError("X public feed", status=status) from None
        except (URLError, OSError, HTTPException, ValueError, TypeError, ElementTree.ParseError):
            raise ServiceError("X public feed") from None

    def fetch_post(self, post_id):
        if post_id not in self.posts:
            raise ServiceError("請先執行公開來源補漏")
        return self.posts[post_id]

    def listen(self):
        raise ServiceError("公開 Feed 僅支援週期性補漏")


def create(*, members, timeout=30):
    feeds = json.loads(os.environ.get("X_PUBLIC_FEEDS", "{}"))
    if not isinstance(feeds, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in feeds.items()):
        raise ValueError("X_PUBLIC_FEEDS 必須是 member_id 至 HTTPS Feed URL 的 JSON object")
    return XPublicSource(members, feeds, timeout=timeout)
