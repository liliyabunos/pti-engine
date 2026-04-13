from __future__ import annotations

import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from perfume_trend_sdk.core.logging.logger import log_event


class FragranticaParser:
    """Parse raw Fragrantica HTML into a structured dict.

    Rules:
    - Never raises on missing fields — returns None/empty instead
    - Deterministic: same input always produces same output
    - No business logic — extraction only
    """

    def parse(self, html: str, source_url: str) -> Dict:
        """Parse a Fragrantica perfume page.

        Args:
            html: Raw HTML string.
            source_url: The URL this HTML was fetched from (passed through).

        Returns:
            Dict with parsed fields. Missing fields are None or empty list.
        """
        result: Dict = {
            "brand_name": None,
            "perfume_name": None,
            "accords": [],
            "notes_top": [],
            "notes_middle": [],
            "notes_base": [],
            "rating_value": None,
            "rating_count": None,
            "source_url": source_url,
            "release_year": None,
            "gender": None,
            "perfumer": None,
            "similar_perfumes": [],
        }

        if not html or not html.strip():
            log_event("INFO", "parse_succeeded", source_url=source_url, source="fragrantica", note="empty_html")
            return result

        try:
            soup = BeautifulSoup(html, "html.parser")
            result["perfume_name"] = self._extract_perfume_name(soup)
            result["brand_name"] = self._extract_brand_name(soup)
            result["accords"] = self._extract_accords(soup)
            result["notes_top"], result["notes_middle"], result["notes_base"] = self._extract_notes(soup)
            result["rating_value"], result["rating_count"] = self._extract_rating(soup)
            result["release_year"] = self._extract_release_year(soup)
            result["gender"] = self._extract_gender(soup)
            result["perfumer"] = self._extract_perfumer(soup)
            result["similar_perfumes"] = self._extract_similar_perfumes(soup)

            log_event("INFO", "parse_succeeded", source_url=source_url, source="fragrantica")
        except Exception as exc:
            log_event("ERROR", "parse_failed", source_url=source_url, source="fragrantica", error=str(exc))

        return result

    # --- Field extractors ---

    def _extract_perfume_name(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract perfume name from h1[itemprop=name]."""
        tag = soup.find("h1", attrs={"itemprop": "name"})
        if tag:
            return tag.get_text(strip=True) or None
        # Fallback: first h1
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True) or None
        return None

    def _extract_brand_name(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract brand name from anchor tag following 'by' text or breadcrumb."""
        # Pattern: <p>by <a href="/designers/...">Brand Name</a></p>
        for p in soup.find_all("p"):
            text = p.get_text()
            if "by " in text:
                link = p.find("a", href=re.compile(r"/designers/"))
                if link:
                    return link.get_text(strip=True) or None
        # Fallback: any link to /designers/
        link = soup.find("a", href=re.compile(r"/designers/"))
        if link:
            return link.get_text(strip=True) or None
        return None

    def _extract_accords(self, soup: BeautifulSoup) -> List[str]:
        """Extract main accords from accord-box divs."""
        accords: List[str] = []
        # Try accord-name divs inside accord-box
        for box in soup.find_all("div", class_="accord-box"):
            name_div = box.find("div", class_="accord-name")
            if name_div:
                text = name_div.get_text(strip=True)
                if text:
                    accords.append(text)
        return accords

    def _extract_notes(self, soup: BeautifulSoup) -> tuple:
        """Extract top, middle, base notes from pyramid section."""
        top: List[str] = []
        middle: List[str] = []
        base: List[str] = []

        pyramid = soup.find(id="pyramid")
        if not pyramid:
            return top, middle, base

        current_section: Optional[List[str]] = None
        for element in pyramid.find_all(["h4", "span"]):
            if element.name == "h4":
                heading = element.get_text(strip=True).lower()
                if "top" in heading:
                    current_section = top
                elif "middle" in heading or "heart" in heading:
                    current_section = middle
                elif "base" in heading:
                    current_section = base
                else:
                    current_section = None
            elif element.name == "span" and current_section is not None:
                text = element.get_text(strip=True)
                if text:
                    current_section.append(text)

        return top, middle, base

    def _extract_rating(self, soup: BeautifulSoup) -> tuple:
        """Extract rating value and count."""
        rating_value: Optional[float] = None
        rating_count: Optional[int] = None

        value_tag = soup.find(attrs={"itemprop": "ratingValue"})
        if value_tag:
            try:
                rating_value = float(value_tag.get_text(strip=True))
            except (ValueError, TypeError):
                pass

        count_tag = soup.find(attrs={"itemprop": "ratingCount"})
        if count_tag:
            try:
                rating_count = int(count_tag.get_text(strip=True).replace(",", ""))
            except (ValueError, TypeError):
                pass

        return rating_value, rating_count

    def _extract_release_year(self, soup: BeautifulSoup) -> Optional[int]:
        """Extract release year from page text."""
        # Look for 4-digit year in paragraphs (e.g. "for women, 2017")
        for p in soup.find_all("p"):
            text = p.get_text()
            match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
            if match:
                return int(match.group(1))
        return None

    def _extract_gender(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract gender hint from page text (for women / for men / unisex)."""
        for p in soup.find_all("p"):
            text = p.get_text(strip=True).lower()
            if "for women" in text:
                return "women"
            elif "for men" in text:
                return "men"
            elif "unisex" in text:
                return "unisex"
        return None

    def _extract_perfumer(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract perfumer name if present."""
        # Look for a link or text near "perfumer" label
        for tag in soup.find_all(string=re.compile(r"[Pp]erfumer")):
            parent = tag.parent
            if parent:
                link = parent.find_next("a")
                if link:
                    return link.get_text(strip=True) or None
        return None

    def _extract_similar_perfumes(self, soup: BeautifulSoup) -> List[str]:
        """Extract list of similar perfume names if present."""
        similar: List[str] = []
        # Look for a section with "similar" heading
        for heading in soup.find_all(["h2", "h3", "h4"]):
            if "similar" in heading.get_text(strip=True).lower():
                # Collect perfume links in the following sibling container
                container = heading.find_next_sibling()
                if container:
                    for link in container.find_all("a"):
                        text = link.get_text(strip=True)
                        if text:
                            similar.append(text)
                break
        return similar
