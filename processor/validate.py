from processor.models import Event, Member
from processor.schemas import ValidationError, validate_schema


def validate_members(members):
    validate_schema(members, "members")
    ids = [member["id"] for member in members]
    if len(ids) != len(set(ids)):
        raise ValidationError("member id 不得重複")
    return [Member(**member) for member in members]


def validate_schedule(schedule, members):
    member_ids = {member.id for member in validate_members(members)}
    validate_schema(schedule, "schedule")
    ids = set()
    for event in schedule["events"]:
        if event["id"] in ids:
            raise ValidationError(f"event id 重複: {event['id']}")
        ids.add(event["id"])
        if event["member_id"] not in member_ids:
            raise ValidationError(f"未知成員: {event['member_id']}")
        if event["time"] is None and event["status"] in {"scheduled", "changed", "live", "finished"}:
            raise ValidationError("已排定直播必須有時間；時間不確定請使用 tbd")
    return [Event(**event) for event in schedule["events"]]


def validate_data(members, schedule, posts, revisions):
    validate_schedule(schedule, members)
    validate_schema(posts, "posts")
    validate_schema(revisions, "revisions")
    member_ids = {member["id"] for member in members}
    event_ids = {event["id"] for event in schedule["events"]}
    post_ids = set()
    post_members = {}
    for post in posts:
        key = (post["source"], post["post_id"])
        if key in post_ids or post["member_id"] not in member_ids:
            raise ValidationError("post 重複或成員不存在")
        post_ids.add(key)
        post_members[key] = post["member_id"]
    # MVP 僅支援 X，事件來源與歷史均必須能回溯至已記錄貼文。
    for event in schedule["events"]:
        if ("x", event["source_post_id"]) not in post_ids:
            raise ValidationError(f"event 缺少來源貼文: {event['id']}")
        if post_members[("x", event["source_post_id"])] != event["member_id"]:
            raise ValidationError("event 來源貼文屬於其他成員")
    for revision in revisions:
        if revision["event_id"] not in event_ids or ("x", revision["source_post_id"]) not in post_ids:
            raise ValidationError("revision 的 event 或來源貼文不存在")
        for snapshot in (revision["before"], revision["after"]):
            if snapshot is None:
                continue
            validate_schedule({"updated_at": revision["timestamp"], "events": [snapshot]}, members)
            if snapshot["id"] != revision["event_id"]:
                raise ValidationError("revision 快照的 event id 不一致")
        after = revision["after"]
        if after["source_post_id"] != revision["source_post_id"] or after["member_id"] != post_members[("x", revision["source_post_id"])]:
            raise ValidationError("revision 的來源貼文不一致")
