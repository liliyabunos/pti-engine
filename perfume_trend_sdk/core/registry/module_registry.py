from typing import Dict, Any
class ModuleRegistry:
    def __init__(self) -> None:
        self._connectors: Dict[str, Any] = {}
        self._normalizers: Dict[str, Any] = {}
        self._extractors: Dict[str, Any] = {}

    def register_connector(self, name: str, connector) -> None:
        self._connectors[name] = connector

    def get_connector(self, name: str):
        return self._connectors[name]

    def register_normalizer(self, name: str, normalizer) -> None:
        self._normalizers[name] = normalizer

    def get_normalizer(self, name: str):
        return self._normalizers[name]

    def register_extractor(self, name: str, extractor) -> None:
        self._extractors[name] = extractor

    def get_extractor(self, name: str):
        return self._extractors[name]
