from typing import Protocol


class EntitiesStore(Protocol):
    def write_entities(self, entities: list) -> None: ...
