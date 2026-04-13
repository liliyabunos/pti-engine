from datetime import datetime

from pydantic import BaseModel


class PipelineContext(BaseModel):
    run_id: str
    workflow_name: str
    started_at: datetime
    environment: str
    schema_version: str
