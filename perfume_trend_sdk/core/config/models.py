from pydantic import BaseModel, Field


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "json"


class StorageConfig(BaseModel):
    raw_backend: str = "filesystem"
    normalized_backend: str = "sqlite"


class AppConfig(BaseModel):
    app_name: str = "perfume_trend_sdk"
    environment: str = "dev"
    schema_version: str = "1.0"
    default_region: str = "US"
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
