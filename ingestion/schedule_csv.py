"""V2.1 公開 CSV 匯入：完整解析後才合併，處理狀態只保存在 repository。"""

import csv
import io
import logging
import re
import unicodedata
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from processor.classify import ConfidencePolicy
from processor.merge import merge_changes
from processor.schemas import ValidationError, load_json, validate_schema
from processor.storage import data_lock, read_unlocked, write_data_unlocked
from processor.validate import validate_data

COLUMNS = ("id", "member_id", "date", "time", "title", "source_url", "created_at")
MAX_CSV_BYTES = 10 * 1024 * 1024
TAIPEI = timezone(timedelta(hours=8))
SPECIAL_TIMES = {"tbd": "tbd", "待定": "tbd", "未定": "tbd", "時間未定": "tbd",
                 "day_off": "day_off", "休息": "day_off", "休息日": "day_off",
                 "unknown": "unknown", "未知": "unknown"}
MONTHS = {name: index for index, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
MONTHS.update({name: index for index, name in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"), 1)})
LOGGER = logging.getLogger(__name__)


def public_url(value, *, https_only=False):
    parts = urlsplit(value)
    if (parts.scheme not in ({"https"} if https_only else {"http", "https"})
            or not parts.hostname or parts.username is not None or parts.password is not None
            or any(char.isspace() or ord(char) < 32 for char in value)):
        raise ValidationError("網址必須是無帳密的公開 HTTP(S) 網址")
    parts.port
    return parts


class PublicRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl, https_only=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_csv(url, *, timeout=30):
    public_url(url, https_only=True)
    request = Request(url, headers={"Accept": "text/csv", "User-Agent": "Meridian-Schedule/2.1"})
    try:
        with build_opener(PublicRedirect()).open(request, timeout=timeout) as response:
            body = response.read(MAX_CSV_BYTES + 1)
    except HTTPError as error:
        error.close()
        raise ValidationError("CSV 下載失敗") from None
    except (URLError, OSError, HTTPException):
        raise ValidationError("CSV 下載失敗") from None
    if len(body) > MAX_CSV_BYTES:
        raise ValidationError("CSV 超過 10 MiB")
    return body.decode("utf-8-sig")


def parse_csv(text):
    try:
        reader = csv.reader(io.StringIO(text.lstrip("\ufeff"), newline=""), strict=True)
        headers = [value.strip() for value in next(reader)]
        if (len(headers) != len(set(headers)) or not set(COLUMNS) <= set(headers)
                or set(headers) - set(COLUMNS) - {"platform", "group", "status"}):
            raise ValidationError("CSV 欄位不符 schedule_ingestion schema")
        rows = []
        for values in reader:
            if not any(value.strip() for value in values):
                continue
            row = dict(zip(headers, (value.strip() for value in values))) if len(values) == len(headers) else None
            rows.append((reader.line_num, row))
        return rows
    except (csv.Error, StopIteration):
        raise ValidationError("CSV 缺少標題列或格式無法解析") from None


def normalize_date(value, reference):
    value = unicodedata.normalize("NFKC", value).strip()
    full = re.fullmatch(r"([0-9]{4})[-/]([0-9]{1,2})[-/]([0-9]{1,2})", value)
    if full:
        return date(*map(int, full.groups())).isoformat()
    short = re.fullmatch(r"([0-9]{1,2})/([0-9]{1,2})", value)
    english = re.fullmatch(r"([A-Za-z]+)\s+([0-9]{1,2})(?:,?\s+([0-9]{4}))?", value)
    if short:
        month, day = map(int, short.groups())
    elif english and english[1].lower() in MONTHS:
        month, day = MONTHS[english[1].lower()], int(english[2])
        if english[3]:
            return date(int(english[3]), month, day).isoformat()
    else:
        raise ValidationError("日期格式無法辨識")
    # 缺少年份時，以資料建立的台灣日期推算，避免重跑或跨年時改變結果。
    candidates = []
    for year in (reference.year - 1, reference.year, reference.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue
    if not candidates:
        raise ValidationError("日期不存在")
    return min(candidates, key=lambda candidate: (abs((candidate - reference).days), candidate)).isoformat()


def _chinese_number(value):
    if value.isascii() and value.isdigit():
        return int(value)
    digits = {char: number for number, char in enumerate("零一二三四五六七八九")}
    digits.update({"〇": 0, "兩": 2})
    if value in digits:
        return digits[value]
    if value.count("十") == 1:
        tens, units = value.split("十")
        if (not tens or tens in digits) and (not units or units in digits):
            return digits.get(tens, 1) * 10 + digits.get(units, 0)
    raise ValidationError("中文時間無法辨識")


def normalize_time(value):
    value = unicodedata.normalize("NFKC", value).strip().lower()
    if value in SPECIAL_TIMES:
        return SPECIAL_TIMES[value]
    clock = re.fullmatch(r"([0-9]{1,2}):([0-9]{2})", value)
    am_pm = re.fullmatch(r"([0-9]{1,2})(?::([0-9]{2}))?\s*([ap])\.?m\.?", value)
    chinese = re.fullmatch(r"(凌晨|早上|上午|中午|下午|晚上|晚間)?([0-9零〇一二兩三四五六七八九十]+)[點時](半|[0-9零〇一二兩三四五六七八九十]+分?)?", value)
    if clock:
        hour, minute = map(int, clock.groups())
    elif am_pm:
        hour, minute = int(am_pm[1]), int(am_pm[2] or 0)
        if not 1 <= hour <= 12:
            raise ValidationError("12 小時制的時數無效")
        hour = hour % 12 + (12 if am_pm[3] == "p" else 0)
    elif chinese:
        period = chinese[1]
        hour = _chinese_number(chinese[2])
        minute = 30 if chinese[3] == "半" else _chinese_number((chinese[3] or "零").rstrip("分"))
        if period:
            if not 1 <= hour <= 12:
                raise ValidationError("中文時段的時數無效")
            hour %= 12
            if period in {"中午", "下午", "晚上", "晚間"} and not (period in {"晚上", "晚間"} and hour == 0):
                hour += 12
    else:
        raise ValidationError("時間格式無法辨識；官方時間未定請填 tbd，無法判定請填 unknown")
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValidationError("時間超出範圍")
    return f"{hour:02d}:{minute:02d}"


def normalize_row(row):
    if row is None:
        raise ValidationError("資料列欄數不符")
    if row.get("status", "pending") not in {"", "pending", "imported", "invalid"}:
        raise ValidationError("status 無效")
    if row.get("status") == "invalid":
        raise ValidationError("status=invalid，略過資料列")
    created = row["created_at"]
    reference = datetime.fromisoformat(created.replace("Z", "+00:00"))
    if reference.tzinfo is None:
        raise ValidationError("created_at 必須包含時區")
    reference = reference.astimezone(TAIPEI)
    normalized = {key: row[key] for key in COLUMNS}
    normalized.update(date=normalize_date(row["date"], reference.date()), time=normalize_time(row["time"]))
    normalized["platform"] = row.get("platform", "").strip().lower() or None
    validate_schema(normalized, "schedule_ingestion")
    normalized["created_at"] = reference.isoformat(timespec="seconds")
    parts = public_url(row["source_url"])
    if parts.hostname.lower() in {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}:
        normalized["source_url"] = "https://x.com" + parts.path.rstrip("/")
    else:
        normalized["source_url"] = urlunsplit(parts._replace(fragment=""))
    validate_schema(normalized, "schedule_ingestion")
    return normalized


def _merge_row(row, values, timestamp, *, platform_only=False):
    if platform_only and row["platform"] is None:
        return False
    time = None if row["time"] in SPECIAL_TIMES else row["time"]
    status = row["time"] if time is None else "scheduled"
    matches = [event for event in values["schedule"]["events"]
               if (event["member_id"], event["date"], event["time"]) == (row["member_id"], row["date"], time)]
    if len(matches) > 1:
        raise ValidationError("同成員、日期與時間有多筆事件，無法唯一比對")
    if matches:
        event = matches[0]
        if platform_only:
            if not any(post["post_id"] == event["source_post_id"] and post["source_url"] == row["source_url"]
                       and post["member_id"] == row["member_id"] for post in values["posts"]):
                raise ValidationError("已匯入列與既有事件的來源不符")
            fields = {"platform": row["platform"]}
        else:
            fields = {"title": row["title"], "status": status}
            if row["platform"] is not None:
                fields["platform"] = row["platform"]
            if status == "scheduled" and event["status"] == "changed":
                fields["status"] = "changed"
        if all(event[key] == value for key, value in fields.items()):
            return False
        if not platform_only and status == "scheduled" and event["status"] in {"cancelled", "postponed", "live", "finished"}:
            raise ValidationError("既有事件已取消、延期、直播中或結束，請人工確認")
        if fields.get("status") == event["status"]:
            fields.pop("status")
        change = {"operation": "update", "match": {"id": event["id"], "member_id": row["member_id"]}, "set": fields}
    elif platform_only:
        return False
    else:
        change = {"operation": "insert", "set": {
            "member_id": row["member_id"], "date": row["date"], "time": time,
            "title": row["title"], "platform": row["platform"], "url": None, "status": status,
        }}
    known = [post for post in values["posts"] if post["source_url"] == row["source_url"]
             and post["member_id"] == row["member_id"]]
    host = urlsplit(row["source_url"]).hostname.lower()
    source = "x" if host == "x.com" else "discord" if host in {"discord.com", "www.discord.com", "discordapp.com"} else "other"
    if platform_only:
        post_id = event["source_post_id"]
    else:
        post_id = known[0]["post_id"] if known else "csv-" + sha256(
            (row["member_id"] + "\n" + row["source_url"]).encode()).hexdigest()
    # CSV 直接匯入不套用舊版信心門檻；平台修正保留原值，其餘以 0.70 相容舊 schema。
    proposal = {"classification": "day_off" if status == "day_off" else "weekly_schedule",
                "confidence": event["confidence"] if platform_only else 0.70,
                "changes": [change], "reason": "schedule_ingestion CSV"}
    result = merge_changes(values["schedule"], proposal, values["members"], source_post_id=post_id,
                           member_id=row["member_id"], timestamp=timestamp, policy=ConfidencePolicy(review_threshold=0.0))
    if not known:
        values["posts"].append({"source": source, "post_id": post_id, "member_id": row["member_id"],
                                "source_url": row["source_url"], "published_at": row["created_at"],
                                "processed_at": timestamp, "type": proposal["classification"],
                                "status": "processed", "media": []})
    values["schedule"] = result.schedule
    values["revisions"].extend(result.revisions)
    return bool(result.revisions)


def import_schedule(text, data_dir, backup_dir, *, timestamp=None):
    rows = parse_csv(text)
    timestamp = timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds")
    data_dir = Path(data_dir)
    report = {"rows": len(rows), "imported": 0, "duplicates": 0, "invalid": 0, "changed": False, "schedule_changed": False}
    with data_lock(data_dir):
        values = read_unlocked(data_dir)
        receipt_path = data_dir / "imported_ids.json"
        imported_ids = load_json(receipt_path) if receipt_path.exists() else []
        validate_schema(imported_ids, "imported_ids")
        seen = set(imported_ids)
        enabled = {member["id"] for member in values["members"] if member["enabled"]}
        normalized = {}
        for line, row in rows:
            try:
                item = normalize_row(row)
                if item["member_id"] not in enabled:
                    raise ValidationError("成員不存在或未啟用")
                normalized.setdefault(item["id"], []).append((line, item))
            except (ValueError, OverflowError, KeyError, TypeError):
                report["invalid"] += 1
                LOGGER.warning("CSV 第 %s 行無效，已略過；請檢查欄位、成員、日期、時間與來源", line)
        for identity, versions in normalized.items():
            line, row = versions[0]
            if any(item != row for _, item in versions):
                report["invalid"] += len(versions)
                LOGGER.warning("CSV 第 %s 行的 id 對應不同內容，整組略過", line)
                continue
            report["duplicates"] += len(versions) - 1
            candidate = deepcopy(values)
            already_imported = identity in seen
            try:
                changed = _merge_row(row, candidate, timestamp, platform_only=already_imported)
                validate_data(candidate["members"], candidate["schedule"], candidate["posts"], candidate["revisions"])
            except ValidationError:
                report["invalid"] += 1
                LOGGER.warning("CSV 第 %s 行無法安全合併，已略過；請檢查既有行程", line)
                continue
            if already_imported and not changed:
                report["duplicates"] += 1
                continue
            values = candidate
            seen.add(identity)
            report["imported"] += 1
            report["schedule_changed"] |= changed
        if seen != set(imported_ids) or report["schedule_changed"]:
            values["imported_ids"] = sorted(seen)
            write_data_unlocked(data_dir, values, backup_dir)
            report["changed"] = True
    return report
