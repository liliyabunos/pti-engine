from typing import Protocol


class RawDataStore(Protocol):
    def write_raw(self, source: str, payload: dict) -> None: ...
