from dataclasses import dataclass


@dataclass(frozen=True)
class ConfidencePolicy:
    auto_threshold: float = 0.95
    review_threshold: float = 0.70
    review_all: bool = True

    def __post_init__(self):
        if not 0 <= self.review_threshold <= self.auto_threshold <= 1:
            raise ValueError("confidence threshold 必須符合 0 <= review <= auto <= 1")

    def decide(self, confidence):
        if confidence < self.review_threshold:
            return "record_only"
        if self.review_all or confidence < self.auto_threshold:
            return "review"
        return "auto"
