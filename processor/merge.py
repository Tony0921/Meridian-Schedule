from copy import deepcopy
from dataclasses import dataclass
from difflib import SequenceMatcher
from hashlib import sha256

from processor.classify import ConfidencePolicy
from processor.schemas import ValidationError, validate_schema
from processor.validate import validate_schedule


@dataclass(frozen=True)
class MergeResult:
    schedule: dict
    revisions: list[dict]
    decision: str


def _minutes(value):
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def _find_event(events, match):
    if "id" not in match and "date" not in match:
        raise ValidationError("update / cancel 必須指定 id 或 date")
    candidates = [event for event in events if event["member_id"] == match["member_id"]]
    for field in ("id", "date", "platform"):
        if field in match:
            candidates = [event for event in candidates if event[field] == match[field]]
    ranked = []
    for event in candidates:
        score = 0
        if "title" in match:
            similarity = SequenceMatcher(None, event["title"].casefold(), match["title"].casefold()).ratio()
            if similarity < 0.6:
                continue
            score += similarity * 2
        if match.get("time") is not None:
            if event["time"] is None:
                continue
            distance = abs(_minutes(event["time"]) - _minutes(match["time"]))
            if distance > 180:
                continue
            score += 1 - distance / 180
        ranked.append((score, event))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked:
        raise ValidationError("找不到相符事件")
    # 候選過於接近時停止整批合併，避免取消或修改錯誤直播。
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.15:
        raise ValidationError("事件比對不明確，請指定 event id")
    return ranked[0][1]


def merge_changes(schedule, proposal, members, *, source_post_id, member_id, timestamp, policy=None):
    validate_schedule(schedule, members)
    validate_schema(proposal, "changes")
    if not isinstance(source_post_id, str) or not source_post_id.strip():
        raise ValidationError("必須提供 source_post_id")
    if member_id not in {member["id"] for member in members if member["enabled"]}:
        raise ValidationError("來源成員不存在或未啟用")
    policy = policy or ConfidencePolicy()
    decision = policy.decide(proposal["confidence"])
    working = deepcopy(schedule)
    revisions = []
    if decision == "record_only":
        return MergeResult(working, revisions, decision)
    if proposal["classification"] in {"irrelevant", "unknown"}:
        if any(change["operation"] != "ignore" for change in proposal["changes"]):
            raise ValidationError("無關或未知貼文不得變更行程")
        return MergeResult(working, revisions, "ignored")
    for change in proposal["changes"]:
        operation = change["operation"]
        if operation == "ignore":
            continue
        fields = deepcopy(change.get("set", {}))
        if fields.get("member_id", member_id) != member_id:
            raise ValidationError("不得修改其他成員的行程")
        if operation == "insert":
            required = {"member_id", "date", "time", "title", "platform", "url", "status"}
            if not required <= fields.keys():
                raise ValidationError(f"insert 缺少欄位: {sorted(required - fields.keys())}")
            identity = (member_id, fields["date"], fields["time"], fields["title"], fields["platform"])
            if any((e["member_id"], e["date"], e["time"], e["title"], e["platform"]) == identity for e in working["events"]):
                continue
            digest = sha256(repr((source_post_id, identity)).encode()).hexdigest()[:12]
            event = {
                **fields,
                "id": f"{member_id}-{fields['date'].replace('-', '')}-{digest}",
                "timezone": fields.get("timezone", "Asia/Taipei"),
                "origin": proposal["classification"],
            }
            before = None
            working["events"].append(event)
        else:
            match = change.get("match", {})
            if match.get("member_id") != member_id:
                raise ValidationError("match 必須指定來源成員")
            event = _find_event(working["events"], match)
            if operation == "cancel" and fields:
                raise ValidationError("cancel 不接受 set，僅變更狀態")
            if operation == "update" and not fields:
                raise ValidationError("update 必須提供 set")
            changes = {"status": "cancelled"} if operation == "cancel" else fields
            if all(event[key] == value for key, value in changes.items()):
                continue
            before = deepcopy(event)
            event.update(changes)
            if operation == "update" and "status" not in fields and event["status"] in {"scheduled", "changed"}:
                event["status"] = "changed"
        event.update(source_post_id=source_post_id, confidence=proposal["confidence"], updated_at=timestamp)
        revisions.append({
            "event_id": event["id"], "timestamp": timestamp, "source_post_id": source_post_id,
            "before": before, "after": deepcopy(event),
        })
    if revisions:
        working["updated_at"] = timestamp
        working["events"].sort(key=lambda event: (event["date"], event["time"] or "99:99", event["id"]))
    # 純函式先在副本套用整批，再驗證；任何錯誤均不修改傳入資料。
    validate_schedule(working, members)
    validate_schema(revisions, "revisions")
    return MergeResult(working, revisions, decision)
