from typing import Protocol


class ScheduleInterpreter(Protocol):
    """Provider 只回傳資料；呼叫端必須驗證，且不得賦予 repository 寫入權。"""

    def classify(self, post: dict) -> dict: ...

    def extract(self, post: dict, current_schedule: dict) -> dict: ...
