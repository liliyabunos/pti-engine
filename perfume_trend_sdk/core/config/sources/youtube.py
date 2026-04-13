from pydantic import BaseModel


class YouTubeSourceConfig(BaseModel):
    api_key: str
    search_queries: list
    max_results: int = 10
