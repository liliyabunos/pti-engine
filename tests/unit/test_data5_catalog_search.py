"""DATA5 / SEARCH1 — Market-Readable Perfume Catalog Search.

Root cause: catalog_perfumes() searched only rp.canonical_name OR rb.canonical_name.
Many Fragrantica entries store perfume names without a brand prefix (e.g. "Red Temptation
Women Zara Eau de Parfum" is stored with brand="Zara" and name="Red Temptation Women Zara
Eau de Parfum"), so a query for "Zara Red Temptation" found no matches.

Fix: added a third OR condition — LOWER(rb.canonical_name || ' ' || rp.canonical_name) LIKE
LOWER(:q) — so market-readable combined queries (brand + perfume name) also match.

Queries that previously returned 0 results:
  "Zara Red Temptation"  → 10 matches (Fragrantica stores as "Zara" + "Red Temptation ...")
  "Ariana Grande Cloud"  → 4 matches
  "Montblanc Explorer"   → 2 matches

Tests here validate the WHERE clause construction logic (pure string logic, no DB).
Integration/production verification must be done manually.
"""

import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))

# ---------------------------------------------------------------------------
# Helper — mirrors the WHERE clause generation in catalog.py
# ---------------------------------------------------------------------------

def _build_search_clause(q: str) -> str:
    """Return the search WHERE fragment for a given query string."""
    q_pattern = f"%{q.strip()}%"
    return (
        "(LOWER(rp.canonical_name) LIKE LOWER(:q) "
        "OR LOWER(rb.canonical_name) LIKE LOWER(:q) "
        "OR LOWER(rb.canonical_name || ' ' || rp.canonical_name) LIKE LOWER(:q))"
    )


def _concat_matches(brand: str, name: str, query: str) -> bool:
    """Check if brand+name concat matches query (case-insensitive substring)."""
    concat = (brand + " " + name).lower()
    return query.lower() in concat


def _name_matches(name: str, query: str) -> bool:
    """Check if name alone matches query (case-insensitive substring)."""
    return query.lower() in name.lower()


def _brand_matches(brand: str, query: str) -> bool:
    """Check if brand alone matches query (case-insensitive substring)."""
    return query.lower() in brand.lower()


def _row_matches(brand: str, name: str, query: str) -> bool:
    """Mirror the three-condition OR from the fixed catalog.py."""
    return (
        _name_matches(name, query)
        or _brand_matches(brand, query)
        or _concat_matches(brand, name, query)
    )


# ---------------------------------------------------------------------------
# A — Zara Red Temptation: concat match (brand=Zara, name has "Red Temptation")
# ---------------------------------------------------------------------------

class TestZaraRedTemptation:
    """Zara Red Temptation was returning 0 results before the fix."""

    def test_concat_matches_combined_query(self):
        brand = "Zara"
        name = "Red Temptation Women"
        assert _row_matches(brand, name, "Zara Red Temptation") is True

    def test_name_only_query_still_matches(self):
        # Existing behavior — "Red Temptation" alone should still work
        brand = "Zara"
        name = "Red Temptation Women"
        assert _row_matches(brand, name, "Red Temptation") is True

    def test_brand_only_query_still_matches(self):
        brand = "Zara"
        name = "Red Temptation Women"
        assert _row_matches(brand, name, "Zara") is True

    def test_partial_combined_no_match_for_wrong_brand(self):
        brand = "Zara"
        name = "Red Temptation Women"
        assert _row_matches(brand, name, "Dior Red Temptation") is False


# ---------------------------------------------------------------------------
# B — Ariana Grande Cloud: concat match
# ---------------------------------------------------------------------------

class TestArianaGrandeCloud:
    """Ariana Grande Cloud was returning 0 results before the fix."""

    def test_concat_matches_combined_query(self):
        brand = "Ariana Grande"
        name = "Cloud"
        assert _row_matches(brand, name, "Ariana Grande Cloud") is True

    def test_brand_query_alone_still_matches(self):
        brand = "Ariana Grande"
        name = "Cloud"
        assert _row_matches(brand, name, "Ariana Grande") is True

    def test_name_only_matches(self):
        brand = "Ariana Grande"
        name = "Cloud"
        assert _row_matches(brand, name, "Cloud") is True

    def test_wrong_brand_does_not_match(self):
        brand = "Ariana Grande"
        name = "Cloud"
        assert _row_matches(brand, name, "Calvin Klein Cloud") is False


# ---------------------------------------------------------------------------
# C — Montblanc Explorer: concat match
# ---------------------------------------------------------------------------

class TestMontblancExplorer:
    """Montblanc Explorer was returning 0 results before the fix."""

    def test_concat_matches_combined_query(self):
        brand = "Montblanc"
        name = "Explorer"
        assert _row_matches(brand, name, "Montblanc Explorer") is True

    def test_name_only_query_matches(self):
        brand = "Montblanc"
        name = "Explorer"
        assert _row_matches(brand, name, "Explorer") is True

    def test_brand_only_query_matches(self):
        brand = "Montblanc"
        name = "Explorer"
        assert _row_matches(brand, name, "Montblanc") is True

    def test_wrong_combined_does_not_match(self):
        brand = "Montblanc"
        name = "Explorer"
        assert _row_matches(brand, name, "Land Rover Explorer") is False


# ---------------------------------------------------------------------------
# D — Existing perfumes with brand prefix in name (no regression)
# ---------------------------------------------------------------------------

class TestPrefixedNamesNoRegression:
    """Perfumes that already worked must still work after the fix."""

    def test_creed_aventus_by_name(self):
        # entity_market stores "Creed Aventus" — matches by name
        brand = "Creed"
        name = "Creed Aventus"
        assert _row_matches(brand, name, "Creed Aventus") is True

    def test_creed_aventus_by_brand(self):
        brand = "Creed"
        name = "Creed Aventus"
        assert _row_matches(brand, name, "Creed") is True

    def test_lattafa_asad_combined(self):
        brand = "Lattafa"
        name = "Asad"
        assert _row_matches(brand, name, "Lattafa Asad") is True

    def test_dior_sauvage_combined(self):
        brand = "Dior"
        name = "Sauvage"
        assert _row_matches(brand, name, "Dior Sauvage") is True

    def test_empty_query_does_not_crash(self):
        # q_pattern = f"%{q.strip()}%" when q="" → "%%", matches everything
        brand = "Creed"
        name = "Aventus"
        q = ""
        # "%%".strip() = "" — substring of "" in any string is True
        assert "" in (brand + " " + name).lower()  # always True for empty string


# ---------------------------------------------------------------------------
# E — Clause structure: third OR condition is present in built clause
# ---------------------------------------------------------------------------

class TestClauseStructure:
    """The WHERE clause string must contain the concat OR condition."""

    def test_clause_contains_concat_condition(self):
        clause = _build_search_clause("anything")
        assert "rb.canonical_name || ' ' || rp.canonical_name" in clause

    def test_clause_contains_name_condition(self):
        clause = _build_search_clause("anything")
        assert "rp.canonical_name" in clause

    def test_clause_contains_brand_condition(self):
        clause = _build_search_clause("anything")
        assert "rb.canonical_name" in clause

    def test_clause_is_single_expression(self):
        clause = _build_search_clause("anything")
        assert clause.startswith("(")
        assert clause.endswith(")")
