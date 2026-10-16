from collections.abc import Iterable
from typing import Protocol


class PostSource(Protocol):
    def listen(self) -> Iterable[dict]: ...

    def fetch_recent(self, account: str, since: str) -> Iterable[dict]: ...

    def fetch_post(self, post_id: str) -> dict: ...
