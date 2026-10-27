import json
from dataclasses import replace
from hashlib import sha256
from urllib.parse import urlsplit

from ingestion.models import CHANGE_COLUMNS
from processor.classify import ConfidencePolicy
from processor.schemas import ValidationError, validate_schema


def _confidence(value):
    if isinstance(value, bool):
        raise ValidationError("confidence 必須是數值，不接受布林值")
    return float(value)


def normalize(post, changes):
    if post.get("post_id") not in (None, "") and not isinstance(post["post_id"], str):
        raise ValidationError("post_id 必須為文字，避免試算表數字精度遺失")
    identity = str(post.get("ingestion_id", "")).strip()
    associated = [row for row in changes if str(row.get("ingestion_id", "")).strip() == identity]
    operations = []
    indexes = set()
    for row in associated:
        if set(row) - set(CHANGE_COLUMNS):
            raise ValidationError("changes 包含未知欄位")
        raw_index = row.get("change_index")
        index = int(raw_index)
        if str(index) != str(raw_index) or index < 0 or index in indexes:
            raise ValidationError("change_index 必須是唯一非負整數")
        indexes.add(index)
        item = {key: value for key, value in row.items()
                if key not in {"ingestion_id", "change_index"} and value != "" and value is not None}
        item["confidence"] = _confidence(row["confidence"])
        for key in ("time", "platform", "url"):
            if item.get(key) == "null" or (item.get("operation") == "insert" and not row.get(key)):
                item[key] = None
        operations.append((index, item))
    if indexes and indexes != set(range(len(indexes))):
        raise ValidationError("change_index 必須從 0 連續編號")
    media = post.get("media_urls") or []
    if isinstance(media, str):
        media = json.loads(media)
    observation = {
        "ingestion_id": identity, "source": post.get("source"),
        "post_id": str(post["post_id"]).strip() if post.get("post_id") else None,
        "member_id": post.get("member_id"), "published_at": post.get("published_at"),
        "discovered_at": post.get("discovered_at"), "source_url": post.get("source_url"),
        "post_text": post.get("post_text") or "", "media_urls": media,
        "classification": post.get("classification"), "confidence": _confidence(post["confidence"]),
        "discovery_source": post.get("discovery_source") or "chatgpt",
        "source_quality": post.get("source_quality") or "unknown",
        "changes": [item for _, item in sorted(operations)],
    }
    validate_observation(observation)
    return observation


def validate_observation(observation):
    validate_schema(observation, "observation")
    if observation["classification"] not in {"irrelevant", "unknown"} and not observation["changes"]:
        raise ValidationError("相關貼文缺少 changes，請先完成擷取")
    for change in observation["changes"]:
        if change["member_id"] != observation["member_id"]:
            raise ValidationError("不得跨成員操作")
    if observation["classification"] in {"irrelevant", "unknown"}:
        if any(change["operation"] != "ignore" for change in observation["changes"]):
            raise ValidationError("無關或未知貼文只能 ignore")


def source_identity(observation):
    post_id = observation["post_id"]
    return post_id or "url-" + sha256(canonical_url(observation["source_url"]).encode()).hexdigest()


def canonical_url(url):
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host in {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}:
        return "https://x.com" + parts.path.rstrip("/").casefold()
    return url.split("#", 1)[0]


def to_fixture(observation):
    validate_observation(observation)
    changes = []
    fields = {"member_id", "date", "time", "title", "platform", "url", "status"}
    for item in observation["changes"]:
        operation = item["operation"]
        change = {"operation": operation}
        if operation == "insert":
            change["set"] = {key: value for key, value in item.items() if key in fields}
        elif operation in {"update", "cancel"}:
            match = {"member_id": item["member_id"]}
            if item.get("match_event_id"):
                match["id"] = item["match_event_id"]
            elif item.get("date"):
                match["date"] = item["date"]
            else:
                raise ValidationError("update / cancel 缺少 match_event_id 或 date")
            if operation == "cancel":
                match.update({key: item[key] for key in ("title", "time", "platform") if key in item})
            else:
                change["set"] = {key: value for key, value in item.items()
                                 if key in fields - {"member_id"} and (key != "date" or "id" in match)}
            change["match"] = match
        changes.append(change)
    confidence = min([observation["confidence"], *[item["confidence"] for item in observation["changes"]]])
    proposal = {"classification": observation["classification"], "confidence": confidence,
                "changes": changes, "reason": "；".join(item["reason"] for item in observation["changes"]) or observation["classification"]}
    validate_schema(proposal, "changes")
    post = {key: observation[key] for key in ("source", "member_id", "published_at", "source_url")}
    post.update(post_id=source_identity(observation), media=[{"type": "image", "url": url} for url in observation["media_urls"]])
    return {"post": post, "proposal": proposal}


def observation_policy(observation, members, policy=None):
    policy = policy or ConfidencePolicy()
    parts = urlsplit(observation["source_url"])
    path = parts.path.strip("/").split("/")
    member = next((item for item in members if item["id"] == observation["member_id"]), {})
    official = (parts.scheme == "https" and parts.hostname in {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}
                and parts.username is None and parts.port in {None, 443} and len(path) == 3 and path[1] == "status"
                and path[0].casefold() == (member.get("x_username") or "").casefold()
                and path[2] == observation["post_id"] and path[2].isdigit())
    if observation["source_quality"] != "primary" or not official:
        return replace(policy, review_all=True)
    return policy
