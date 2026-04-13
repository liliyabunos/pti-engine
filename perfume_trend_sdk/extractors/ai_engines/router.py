from perfume_trend_sdk.extractors.ai_engines.openai_extractor import OpenAIExtractor


def get_extractor(provider: str, model: str = None, temperature: float = 0):
    if provider == "openai":
        return OpenAIExtractor(model=model or "gpt-4o-mini", temperature=temperature)
    elif provider == "claude":
        raise NotImplementedError("Claude extractor not implemented yet")
    elif provider == "gemini":
        raise NotImplementedError("Gemini extractor not implemented yet")
    else:
        raise ValueError(f"Unknown provider: {provider}")
