from __future__ import annotations

import re
import urllib.parse

BASE_URL = "https://www.fragrantica.com"


def slugify(text: str) -> str:
    """Lowercase, replace spaces with dashes, strip special chars."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def build_perfume_url(brand_slug: str, perfume_slug: str) -> str:
    """Build a Fragrantica perfume page URL from brand and perfume slugs."""
    return f"{BASE_URL}/perfume/{brand_slug}/{perfume_slug}.html"


def build_search_url(query: str) -> str:
    """Build a Fragrantica search URL for a given query string."""
    encoded = urllib.parse.quote_plus(query)
    return f"{BASE_URL}/search/?query={encoded}"
