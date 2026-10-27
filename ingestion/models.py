from dataclasses import dataclass
from typing import Protocol


POST_COLUMNS = (
    "ingestion_id", "source", "post_id", "member_id", "published_at", "discovered_at",
    "source_url", "post_text", "media_urls", "classification", "confidence", "status",
    "processed_at", "processor_result", "discovery_source", "source_quality",
)
CHANGE_COLUMNS = (
    "ingestion_id", "change_index", "operation", "member_id", "date", "time", "title",
    "platform", "url", "status", "confidence", "match_event_id", "reason",
)
QUEUE_STATUSES = {"new", "processing", "processed", "ignored", "review", "failed", "duplicate"}


@dataclass(frozen=True)
class QueueSnapshot:
    posts: list[dict]
    changes: list[dict]


class ObservationSource(Protocol):
    def read(self) -> QueueSnapshot: ...

    def update(self, ingestion_id: str, *, status: str, processed_at: str, processor_result: str) -> None: ...
