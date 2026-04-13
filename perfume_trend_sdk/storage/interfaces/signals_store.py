from typing import Protocol


class SignalsStore(Protocol):
    def write_signals(self, signals: list) -> None: ...
