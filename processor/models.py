from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Member:
    id: str
    name: str
    group: str
    group_name: str
    x_username: str | None
    youtube: str | None
    twitch: str | None
    enabled: bool


@dataclass(frozen=True)
class Event:
    id: str
    member_id: str
    date: str
    time: str | None
    timezone: str
    title: str
    platform: str | None
    url: str | None
    status: str
    origin: str
    source_post_id: str
    confidence: float
    updated_at: str
    source_url: str | None = None
    created_at: str | None = None

    def to_dict(self):
        return asdict(self)
