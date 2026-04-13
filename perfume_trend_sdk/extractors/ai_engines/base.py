from typing import Protocol


class AIExtractor(Protocol):
    def extract(self, text: str) -> dict:
        ...
