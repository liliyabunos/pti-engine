from typing import Protocol


class NormalizedDataStore(Protocol):
    def write_normalized(self, items: list) -> None: ...
