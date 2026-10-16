import os
from importlib import import_module
from typing import Protocol


class InterpreterError(ValueError):
    """AI 服務失敗或未回傳可供驗證的提案。"""


class ScheduleInterpreter(Protocol):
    """Provider 只回傳資料；呼叫端必須驗證，且不得賦予 repository 寫入權。"""

    # post 包含 member、post_text、published_at、images（HTTPS 或 data URL）。
    def classify(self, post: dict) -> dict: ...

    # extract 一次回傳 classification、confidence、changes、reason，避免重複 API 請求。
    def extract(self, post: dict, current_schedule: dict) -> dict: ...


def create_interpreter(name="openai", *, model=None, timeout=60) -> ScheduleInterpreter:
    if name == "openai":
        from processor.openai_provider import OpenAIInterpreter

        return OpenAIInterpreter(model=model or os.environ.get("OPENAI_MODEL"),
                                 api_key=os.environ.get("OPENAI_API_KEY"), timeout=timeout)
    try:
        module_name, factory_name = name.split(":")
        factory = getattr(import_module(module_name), factory_name)
    except (ValueError, ImportError, AttributeError):
        raise InterpreterError("Provider 必須是 openai 或可匯入的 module:factory") from None
    if not callable(factory):
        raise InterpreterError("Provider factory 必須可呼叫")
    return factory(model=model, timeout=timeout)
