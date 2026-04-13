import json
import os
import urllib.request

OPENAI_API_URL = "https://api.openai.com/v1/responses"

SYSTEM_PROMPT = """You are a perfume intelligence extractor.
Extract structured data from the given text.
Return JSON only. No explanations.

Rules:
- detect perfume product names
- detect brand names
- detect fragrance notes if mentioned
- infer overall sentiment: positive, negative, or neutral
- if nothing found, return empty lists and confidence 0.0"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "perfumes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "brand": {"type": "string"},
                    "product": {"type": "string"},
                    "confidence": {"type": "number"},
                    "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]},
                },
                "required": ["brand", "product", "confidence", "sentiment"],
                "additionalProperties": False,
            },
        },
        "brands": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "array", "items": {"type": "string"}},
        "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]},
        "confidence": {"type": "number"},
    },
    "required": ["perfumes", "brands", "notes", "sentiment", "confidence"],
    "additionalProperties": False,
}

EMPTY_RESULT = {
    "perfumes": [],
    "brands": [],
    "notes": [],
    "sentiment": "neutral",
    "confidence": 0.0,
}


class OpenAIExtractor:
    def __init__(self, model: str = "gpt-4o-mini", temperature: float = 0) -> None:
        self.model = model
        self.temperature = temperature

    def extract(self, text: str) -> dict:
        if not text or not text.strip():
            return EMPTY_RESULT

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            print("OpenAIExtractor: OPENAI_API_KEY not set")
            return EMPTY_RESULT

        body = json.dumps({
            "model": self.model,
            "input": text,
            "instructions": SYSTEM_PROMPT,
            "temperature": self.temperature,
            "max_output_tokens": 300,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "perfume_extraction",
                    "strict": True,
                    "schema": OUTPUT_SCHEMA,
                }
            },
        }).encode("utf-8")

        req = urllib.request.Request(
            OPENAI_API_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode("utf-8"))
            raw_text = data["output"][0]["content"][0]["text"]
            return json.loads(raw_text)
        except Exception as e:
            print("OpenAIExtractor error:", str(e))
            return EMPTY_RESULT
