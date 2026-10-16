"""以標準函式庫驗證本專案 JSON Schema 使用的關鍵字。"""

import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"


class ValidationError(ValueError):
    pass


def load_json(path: Path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _format_valid(value, name):
    try:
        if name == "date":
            return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)) and bool(date.fromisoformat(value))
        if name == "date-time":
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value) is None:
                return False
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.tzinfo is not None
        if name == "uri":
            parsed = urlsplit(value)
            return parsed.scheme in {"https", "http"} and bool(parsed.netloc) and re.search(r"\s", value) is None
    except ValueError:
        return False
    raise ValidationError(f"未支援的 format: {name}")


def _validate(value, schema, root, path):
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            raise ValidationError("僅支援本地 JSON Schema reference")
        target = root
        for part in ref[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        _validate(value, target, root, path)
        return
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    checks = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "null": value is None,
        "number": type(value) in (int, float) and math.isfinite(value),
        "integer": type(value) is int,
    }
    if types and not any(checks.get(kind, False) for kind in types):
        raise ValidationError(f"{path}: 型別必須為 {types}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValidationError(f"{path}: 不允許的值 {value!r}")
    if "const" in schema and value != schema["const"]:
        raise ValidationError(f"{path}: 必須為 {schema['const']!r}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise ValidationError(f"{path}: 缺少 {key}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = set(value) - set(properties)
            if extras:
                raise ValidationError(f"{path}: 未知欄位 {sorted(extras)}")
        for key, item in value.items():
            if key in properties:
                _validate(item, properties[key], root, f"{path}.{key}")
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ValidationError(f"{path}: 項目數不足")
        for index, item in enumerate(value):
            _validate(item, schema.get("items", {}), root, f"{path}[{index}]")
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise ValidationError(f"{path}: 字串太短")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise ValidationError(f"{path}: 格式不符")
        if "format" in schema and not _format_valid(value, schema["format"]):
            raise ValidationError(f"{path}: {schema['format']} 格式不符")
    elif type(value) in (int, float):
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            raise ValidationError(f"{path}: 數值超出範圍")


def validate_schema(value, name):
    schema = load_json(SCHEMA_DIR / f"{name}.schema.json")
    _validate(value, schema, schema, name)
