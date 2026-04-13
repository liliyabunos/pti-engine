import yaml

from .models import AppConfig


def load_yaml(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def load_app_config(path: str) -> AppConfig:
    data = load_yaml(path)
    return AppConfig(**data)
