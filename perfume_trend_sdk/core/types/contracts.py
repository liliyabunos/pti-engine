from typing import Protocol


class SourceConnector(Protocol):
    name: str

    def validate_config(self, config: dict) -> None: ...
    def fetch(self) -> dict: ...


class Normalizer(Protocol):
    def normalize(self, raw_item: dict) -> dict: ...


class Extractor(Protocol):
    def extract(self, item: dict) -> dict: ...


class Resolver(Protocol):
    def resolve(self, signals: dict) -> dict: ...


class Enricher(Protocol):
    def enrich(self, entity: dict) -> dict: ...


class Scorer(Protocol):
    def score(self, entity: dict) -> dict: ...


class Publisher(Protocol):
    def publish(self, payload: dict) -> None: ...
