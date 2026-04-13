from typing import Protocol


class AnalyticsStore(Protocol):
    def write_analytics(self, report: dict) -> None: ...
