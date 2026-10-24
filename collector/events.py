import re

from processor.schemas import ValidationError


def validate_event(event):
    if not isinstance(event, dict) or set(event) != {"source", "post_id", "member_id"} or event["source"] != "x":
        raise ValidationError("事件只能包含 source:x、post_id、member_id")
    for field in ("post_id", "member_id"):
        if not isinstance(event[field], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", event[field]):
            raise ValidationError("事件識別碼格式不正確")
    return dict(event)
