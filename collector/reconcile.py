import json
from datetime import datetime, timedelta, timezone

TAIPEI = timezone(timedelta(hours=8))


def reconcile(source, store, members, now, *, lookback=172800, due_only=False, hours=(6, 18)):
    if not hours or any(type(hour) is not int or not 0 <= hour <= 23 for hour in hours):
        raise ValueError("補漏時段必須是 0～23 的台灣小時")
    local = datetime.fromtimestamp(now, TAIPEI)
    slots = [local.replace(hour=hour, minute=0, second=0, microsecond=0) for hour in hours]
    slots.append((local - timedelta(days=1)).replace(hour=max(hours), minute=0, second=0, microsecond=0))
    latest_slot = max(slot.timestamp() for slot in slots if slot.timestamp() <= now)
    failures = 0
    for member in members:
        if not member["enabled"]:
            continue
        previous = store.scan_time(member["id"])
        attempted = store.report()["heartbeats"].get("scan_attempt:" + member["id"], 0)
        if due_only and ((previous is not None and previous >= latest_slot) or now - attempted < 300):
            continue
        since = max(now - lookback, previous - 3600 if previous is not None else now - lookback)
        since_iso = datetime.fromtimestamp(since, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        store.heartbeat("scan_attempt:" + member["id"], now)
        try:
            for event in source.fetch_recent(member, since_iso):
                if event["member_id"] != member["id"]:
                    raise ValueError("補漏來源成員不一致")
                store.enqueue(event, now)
            # 分頁完整取得後才前進 checkpoint，失敗的掃描會保留原 checkpoint。
            store.scanned(member["id"], now)
        except Exception as error:
            failures += 1
            print(json.dumps({"timestamp": now, "member_id": member["id"], "operation": "reconcile",
                              "result": "failed", "error": type(error).__name__}))
    return failures
