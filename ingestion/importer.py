from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from collector.http import ServiceError
from ingestion.dedupe import IngestionStore
from ingestion.models import QUEUE_STATUSES
from ingestion.normalize import canonical_url, normalize, observation_policy, source_identity, to_fixture
from processor.merge import MergeConflict
from processor.schemas import ValidationError, load_json
from processor.storage import atomic_json, data_lock, fingerprint, read_data
from scripts.process_post import process_fixture


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def import_queue(source, data_dir, state_dir, *, timestamp=None, policy=None, publisher=None, retry_ingestion=None):
    timestamp = timestamp or now_iso()
    data_dir, state_dir = Path(data_dir).resolve(), Path(state_dir).resolve()
    if state_dir.is_relative_to(data_dir) or state_dir.is_relative_to(Path(__file__).resolve().parents[1] / "data"):
        raise ValidationError("匯入狀態與提案必須位於正式資料目錄之外")
    snapshot = source.read()
    ids = [row.get("ingestion_id") for row in snapshot.posts]
    if any(not isinstance(value, str) or not value.strip() for value in ids) or len(ids) != len(set(ids)):
        raise ValidationError("posts 的 ingestion_id 缺少或重複")
    if retry_ingestion and retry_ingestion not in ids:
        raise ValidationError("指定的 ingestion_id 不在 queue 中")
    state_dir.mkdir(parents=True, exist_ok=True)
    results = []
    with data_lock(state_dir):
        store = IngestionStore(state_dir / "ingestion.db")
        try:
            values = read_data(data_dir)
            store.set_meta("last_sheet_read", timestamp)
            discovered = [row["discovered_at"] for row in snapshot.posts
                          if row.get("discovery_source", "chatgpt") == "chatgpt" and row.get("discovered_at")]
            if discovered:
                try:
                    latest = max(discovered, key=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")))
                    store.set_meta("last_chatgpt_ingestion", latest)
                except (ValueError, TypeError, AttributeError):
                    pass
            for row in snapshot.posts:
                ingestion_id = row["ingestion_id"]
                try:
                    existing = store.get(ingestion_id)
                    if row.get("status") not in QUEUE_STATUSES:
                        raise ValidationError("Queue status 無效")
                    if existing and (not existing["published"] or existing["status"] != "processed") and any((post["source"], post["post_id"]) == (existing["source"], existing["external_post_id"])
                                        or canonical_url(post["source_url"]) == existing["source_url"] for post in values["posts"]):
                        store.published(ingestion_id, {"result": "duplicate"}, timestamp)
                        existing = store.get(ingestion_id)
                    retry = ingestion_id == retry_ingestion
                    if retry:
                        normalize(row, snapshot.changes)
                        if existing:
                            store.retry(ingestion_id)
                        existing = None
                        row["status"] = "new"
                    if existing and existing["status"] != "processing":
                        if row["status"] == "new" and existing["status"] != "failed" and fingerprint(normalize(row, snapshot.changes)) != existing["payload_hash"]:
                            raise ValidationError("已完成的 ingestion 內容已變更，請使用 --retry-ingestion")
                        if row["status"] == "new" and existing["status"] == "failed":
                            with store.db:
                                store.db.execute("DELETE FROM ingestion WHERE ingestion_id=? AND status='failed'", (ingestion_id,))
                            existing = None
                        else:
                            _sync(source, row, existing)
                            results.append({"ingestion_id": ingestion_id, "result": existing["status"], "reused": True})
                            continue
                    if row["status"] != "new" and not (row["status"] == "processing" and existing):
                        continue
                    identity = {key: row.get(key) for key in ("source", "post_id", "source_url")}
                    if identity["source"] != "x" or not isinstance(identity["source_url"], str):
                        raise ValidationError("來源欄位無效")
                    if identity["post_id"] and not isinstance(identity["post_id"], str):
                        raise ValidationError("post_id 必須為文字")
                    known = any((post["source"], post["post_id"]) == (identity["source"], source_identity(identity))
                                or canonical_url(post["source_url"]) == canonical_url(identity["source_url"])
                                for post in values["posts"])
                    if not existing and (known or store.duplicate(identity)):
                        _update(source, row, "duplicate", timestamp, "duplicate")
                        results.append({"ingestion_id": ingestion_id, "result": "duplicate"})
                        continue
                    observation = normalize(row, snapshot.changes)
                    fixture = to_fixture(observation)
                    digest = fingerprint(observation)
                    if existing and existing["payload_hash"] != digest:
                        raise ValidationError("處理中的 ingestion 內容已變更，請先人工檢查")
                    if not existing:
                        output = state_dir / observation["ingestion_id"] / ("retry-" + uuid4().hex if retry else "current") / "proposal.json"
                        store.reserve(observation, digest, timestamp, output)
                    else:
                        output = Path(existing["proposal"])
                    _update(source, row, "processing", timestamp, "processing")
                    if output.exists():
                        bundle = load_json(output)
                        if bundle.get("observation") != observation:
                            raise ValidationError("既有提案與 ingestion 不一致")
                    else:
                        try:
                            selected_policy = observation_policy(observation, values["members"], policy)
                            bundle = process_fixture(fixture, data_dir, timestamp, selected_policy)
                        except MergeConflict as error:
                            bundle = {**fixture, "decision": "review", "merge_error": str(error)}
                        bundle["observation"] = observation
                        atomic_json(bundle, output)
                    decision = bundle["decision"]
                    status = {"review": "review", "record_only": "review", "ignored": "ignored", "auto": "processed"}[decision]
                    result = "merge_conflict" if bundle.get("merge_error") else decision
                    store.finish(ingestion_id, status, timestamp, result, output)
                    _update(source, row, status, timestamp, result)
                    results.append({"ingestion_id": ingestion_id, "result": status, "decision": decision, "proposal": str(output)})
                except Exception as error:
                    # 已完成的 receipt 不因 Sheet 回寫失敗退回 failed，下一次沿用提案重試回寫。
                    receipt = store.get(ingestion_id)
                    if not isinstance(error, (ServiceError, OSError)) and (receipt is None or receipt["status"] == "processing"):
                        if receipt:
                            store.finish(ingestion_id, "failed", timestamp, type(error).__name__)
                        try:
                            _update(source, row, "failed", timestamp, type(error).__name__)
                        except Exception:
                            pass
                    results.append({"ingestion_id": ingestion_id, "result": "failed", "error": type(error).__name__})
            if publisher:
                for receipt in store.unpublished():
                    if any(result["ingestion_id"] == receipt["ingestion_id"] and result["result"] == "failed" for result in results):
                        continue
                    try:
                        bundle = load_json(Path(receipt["proposal"]))
                        if "base_hash" not in bundle or bundle["decision"] == "record_only":
                            continue
                        published = publisher(bundle)
                        store.published(receipt["ingestion_id"], published, timestamp)
                        row = next((item for item in snapshot.posts if item["ingestion_id"] == receipt["ingestion_id"]), None)
                        if row:
                            _sync(source, row, store.get(receipt["ingestion_id"]))
                    except Exception as error:
                        results.append({"ingestion_id": receipt["ingestion_id"], "result": "failed", "error": type(error).__name__})
            store.set_meta("queue_counts", dict(Counter(row.get("status", "unknown") for row in snapshot.posts)))
            store.set_meta("processing_since", [row.get("processed_at") or row.get("discovered_at")
                                                for row in snapshot.posts if row.get("status") == "processing"])
        finally:
            store.close()
    return results


def _update(source, row, status, timestamp, result):
    updates = {"status": status, "processed_at": timestamp, "processor_result": result}
    source.update(row["ingestion_id"], **updates)
    row.update(updates)


def _sync(source, row, receipt):
    updates = {key: receipt[key] for key in ("status", "processed_at", "processor_result")}
    if any(row.get(key) != value for key, value in updates.items()):
        source.update(row["ingestion_id"], **updates)
        row.update(updates)
