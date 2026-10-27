"""正式資料與選配匯入 ID 共用檔案鎖、備份及中斷復原日誌。"""

import base64
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from processor.schemas import ValidationError, load_json, validate_schema
from processor.validate import validate_data

NAMES = ("members", "schedule", "posts", "revisions")


def atomic_json(value, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def fingerprint(values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


@contextmanager
def data_lock(directory):
    directory = Path(directory)
    with (directory / ".update.lock").open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValidationError("資料正由另一個程序使用，請稍後重試") from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def read_unlocked(directory):
    if (directory / ".transaction.json").exists():
        raise ValidationError("存在未完成寫入，請先執行 recover")
    values = {name: load_json(directory / f"{name}.json") for name in NAMES}
    validate_data(*(values[name] for name in NAMES))
    if (directory / "imported_ids.json").exists():
        validate_schema(load_json(directory / "imported_ids.json"), "imported_ids")
    return values


def read_data(directory):
    directory = Path(directory)
    with data_lock(directory):
        return read_unlocked(directory)


def snapshot(directory, backup_dir):
    directory, backup_dir = Path(directory).resolve(), Path(backup_dir).resolve()
    if backup_dir == directory or backup_dir.is_relative_to(directory):
        raise ValidationError("備份必須位於資料目錄之外")
    values = read_unlocked(directory)
    if (directory / "imported_ids.json").exists():
        values["imported_ids"] = load_json(directory / "imported_ids.json")
    original = {name: base64.b64encode((directory / f"{name}.json").read_bytes()).decode() for name in values}
    path = backup_dir / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex + ".json")
    atomic_json({"version": 1, "data": values, "hash": fingerprint(values), "original": original}, path)
    return path


def load_snapshot(path):
    backup = load_json(Path(path))
    values = backup["data"]
    if (backup.get("version") != 1 or set(values) not in (set(NAMES), set(NAMES) | {"imported_ids"})
            or backup.get("hash") != fingerprint(values)):
        raise ValidationError("備份格式或校驗值錯誤")
    validate_data(*(values[name] for name in NAMES))
    if "imported_ids" in values:
        validate_schema(values["imported_ids"], "imported_ids")
    for name in values:
        if json.loads(base64.b64decode(backup["original"][name], validate=True)) != values[name]:
            raise ValidationError("備份原始內容不一致")
    return backup


def recover_unlocked(directory):
    journal = directory / ".transaction.json"
    if not journal.exists():
        return False
    # 日誌內嵌原始內容，不接受其中指定任意檔案路徑。
    backup = load_snapshot(journal)
    for name in backup["data"]:
        target = directory / f"{name}.json"
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(base64.b64decode(backup["original"][name], validate=True))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    if "imported_ids" not in backup["data"]:
        (directory / "imported_ids.json").unlink(missing_ok=True)
    journal.unlink()
    return True


def write_data_unlocked(directory, values, backup_dir):
    validate_data(*(values[name] for name in NAMES))
    if "imported_ids" in values:
        validate_schema(values["imported_ids"], "imported_ids")
    backup_path = snapshot(directory, backup_dir)
    journal = directory / ".transaction.json"
    atomic_json(load_snapshot(backup_path), journal)
    try:
        names = (*NAMES, "imported_ids") if "imported_ids" in values else NAMES
        for name in names:
            atomic_json(values[name], directory / f"{name}.json")
        journal.unlink()
    except BaseException:
        recover_unlocked(directory)
        raise
    return backup_path
