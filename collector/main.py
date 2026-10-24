import argparse
import json
import os
import queue
import threading
import time
from pathlib import Path

from collector.dedupe import PostStore
from collector.github_dispatch import GitHubClient
from collector.reconcile import reconcile
from collector.sources import create_source
from processor.schemas import load_json
from processor.validate import validate_members

ROOT = Path(__file__).resolve().parents[1]


def drain(store, dispatcher, now, *, limit=100, clock=None):
    failures = 0
    for _ in range(limit):
        now = clock() if clock else now
        event = store.claim(now)
        if event is None:
            break
        try:
            dispatcher.dispatch(event)
        except Exception as error:
            failures += 1
            store.fail(event, clock() if clock else now, retry_after=getattr(error, "retry_after", 0))
            result = "failed"
        else:
            store.complete(event, clock() if clock else now)
            result = "dispatched"
        print(json.dumps({"timestamp": now, **event, "operation": "dispatch", "result": result}))
    return failures


def listen_worker(source, inbox):
    delay = 1
    while True:
        try:
            for event in source.listen():
                inbox.put(("event", event))
                delay = 1
        except Exception as error:
            inbox.put(("error", type(error).__name__))
            delay = max(delay, getattr(error, "retry_after", 0))
        else:
            inbox.put(("error", "StreamEnded"))
        time.sleep(delay)
        delay = min(max(delay * 2, 1), 300)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Collector：事件接收、SQLite 去重、dispatch 與補漏")
    parser.add_argument("mode", choices=("listen", "reconcile", "retry", "requeue", "setup-rules"))
    parser.add_argument("--source", default=os.environ.get("POST_SOURCE", "x-api"))
    parser.add_argument("--members", type=Path, default=ROOT / "data/members.json")
    parser.add_argument("--db", type=Path, default=ROOT / ".local/collector.db")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--once", action="store_true", help="JSONL 重播完畢後結束")
    parser.add_argument("--lookback-hours", type=int, default=48)
    parser.add_argument("--post-id", help="人工重送的失敗貼文 id")
    parser.add_argument("--reconcile-hours", default=os.environ.get("RECONCILE_HOURS", "6,18"))
    args = parser.parse_args(argv)
    if args.lookback_hours < 1:
        parser.error("lookback-hours 必須為正數")
    if args.once and args.mode == "listen" and args.source != "jsonl":
        parser.error("listen --once 僅適用於 JSONL")
    if args.mode == "requeue" and not args.post_id:
        parser.error("requeue 必須指定 --post-id")
    store = None
    try:
        hours = tuple(int(hour) for hour in args.reconcile_hours.split(","))
        if not hours or any(not 0 <= hour <= 23 for hour in hours):
            raise ValueError("補漏時段不正確")
        members = load_json(args.members)
        validate_members(members)
        if args.mode == "setup-rules":
            source = create_source(args.source, members)
            source.setup_rules()
            return 0
        dispatcher = GitHubClient(args.repository or "", os.environ.get("GITHUB_TOKEN"))
        store = PostStore(args.db)
        if args.mode == "requeue":
            store.requeue(args.post_id, time.time())
        if args.mode in {"retry", "requeue"}:
            return int(bool(drain(store, dispatcher, time.time(), clock=time.time)))
        source = create_source(args.source, members)
        if args.mode == "reconcile":
            failures = reconcile(source, store, members, time.time(), lookback=args.lookback_hours * 3600)
            failures += drain(store, dispatcher, time.time(), clock=time.time)
            return int(bool(failures))
        if args.once:
            for event in source.listen():
                if event is not None:
                    store.enqueue(event, time.time())
            return int(bool(drain(store, dispatcher, time.time(), clock=time.time)))
        inbox = queue.Queue(maxsize=1000)
        threading.Thread(target=listen_worker, args=(source, inbox), daemon=True).start()
        while True:
            now = time.time()
            try:
                kind, value = inbox.get(timeout=5)
                if kind == "event":
                    store.heartbeat("source", now)
                    if value is not None:
                        try:
                            if value["member_id"] not in {m["id"] for m in members if m["enabled"]}:
                                raise ValueError("未知來源成員")
                            store.enqueue(value, now)
                        except (ValueError, KeyError, TypeError):
                            print(json.dumps({"timestamp": now, "result": "invalid_event"}))
                else:
                    print(json.dumps({"timestamp": now, "operation": "listen", "result": "reconnecting", "error": value}))
            except queue.Empty:
                pass
            store.heartbeat("collector", time.time())
            reconcile(source, store, members, now, lookback=args.lookback_hours * 3600, due_only=True, hours=hours)
            drain(store, dispatcher, now, limit=10, clock=time.time)
            store.heartbeat("collector", time.time())
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print(json.dumps({"timestamp": time.time(), "result": "failed", "error": type(error).__name__}))
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
