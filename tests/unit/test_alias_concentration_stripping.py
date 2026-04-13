from __future__ import annotations

"""
Tests for concentration-stripped short alias generation.

Coverage:
  - strip_concentration(): all suffix patterns, dash notation, no-op on clean names
  - generate_perfume_aliases(): short aliases present alongside long forms
  - Cross-brand collision safety: two perfumes with same stripped base emit
    separate alias rows (one per entity_id)
  - Determinism: same input always produces the same alias set
  - End-to-end resolver: short mentions resolve after DB rebuild
"""

from pathlib import Path

import pytest

from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import PerfumeResolver
from perfume_trend_sdk.utils.alias_generator import (
    generate_perfume_aliases,
    strip_concentration,
)
from perfume_trend_sdk.workflows.load_fragrance_master import ingest_seed_csv


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SEED = (
    "fragrance_id,brand_name,perfume_name,source\n"
    "fr_1,Serge Lutens,Ambre Sultan Eau de Parfum,test\n"
    "fr_2,Diptyque,Philosykos - Eau de Parfum,test\n"
    "fr_3,Parfums de Marly,Layton Eau de Parfum,test\n"
    "fr_4,Dior,Sauvage,test\n"                           # no concentration — unchanged
    "fr_5,Creed,Aventus,test\n"
    "fr_6,Maison Francis Kurkdjian,Baccarat Rouge 540 Extrait de Parfum,test\n"
    "fr_7,Tom Ford,Black Orchid Parfum,test\n"
    # Collision test: two perfumes whose stripped base would be "rose"
    "fr_8,Diptyque,Rose Eau de Parfum,test\n"
    "fr_9,Byredo,Rose Eau de Parfum,test\n"
)


@pytest.fixture()
def resolver(tmp_path: Path) -> PerfumeResolver:
    csv_path = tmp_path / "seed.csv"
    db_path = tmp_path / "db.sqlite"
    csv_path.write_text(_SEED)
    ingest_seed_csv(csv_path, db_path)
    return PerfumeResolver(str(db_path))


# ---------------------------------------------------------------------------
# strip_concentration
# ---------------------------------------------------------------------------

class TestStripConcentration:
    def test_removes_eau_de_parfum_suffix(self):
        assert strip_concentration("Ambre Sultan Eau de Parfum") == "Ambre Sultan"

    def test_removes_eau_de_toilette_suffix(self):
        assert strip_concentration("Philosykos Eau de Toilette") == "Philosykos"

    def test_removes_dash_concentration_notation(self):
        assert strip_concentration("Philosykos - Eau de Parfum") == "Philosykos"

    def test_removes_extrait_suffix(self):
        assert strip_concentration("Baccarat Rouge 540 Extrait de Parfum") == "Baccarat Rouge 540"

    def test_removes_parfum_suffix(self):
        assert strip_concentration("Black Orchid Parfum") == "Black Orchid"

    def test_removes_body_spray_suffix(self):
        assert strip_concentration("Libre Body Spray") == "Libre"

    def test_removes_edt_abbreviation(self):
        assert strip_concentration("Sauvage EDT") == "Sauvage"

    def test_removes_edp_abbreviation(self):
        assert strip_concentration("Sauvage EDP") == "Sauvage"

    def test_no_op_on_clean_name(self):
        assert strip_concentration("Sauvage") == "Sauvage"
        assert strip_concentration("Aventus") == "Aventus"
        assert strip_concentration("Baccarat Rouge 540") == "Baccarat Rouge 540"

    def test_multiword_base_preserved(self):
        assert strip_concentration("Baccarat Rouge 540 Eau de Parfum") == "Baccarat Rouge 540"

    def test_is_deterministic(self):
        name = "Ambre Sultan Eau de Parfum"
        results = {strip_concentration(name) for _ in range(5)}
        assert len(results) == 1


# ---------------------------------------------------------------------------
# generate_perfume_aliases — short alias presence
# ---------------------------------------------------------------------------

class TestGeneratePerfumeAliasesShortForms:
    def test_ambre_sultan_short_alias_present(self):
        aliases = generate_perfume_aliases("Serge Lutens", "Ambre Sultan Eau de Parfum")
        assert "ambre sultan" in aliases

    def test_ambre_sultan_brand_short_alias_present(self):
        aliases = generate_perfume_aliases("Serge Lutens", "Ambre Sultan Eau de Parfum")
        assert "serge lutens ambre sultan" in aliases

    def test_philosykos_brand_short_alias_present(self):
        """1-token stripped base: bare 'philosykos' is NOT added (false-positive guard).
        Brand-prefixed 'diptyque philosykos' IS added and is specific enough."""
        aliases = generate_perfume_aliases("Diptyque", "Philosykos - Eau de Parfum")
        assert "diptyque philosykos" in aliases
        # Bare 1-token base excluded to prevent generic-word false matches
        assert "philosykos" not in aliases

    def test_layton_brand_short_alias_present(self):
        """1-token stripped base: bare 'layton' NOT added; brand-prefixed forms are."""
        aliases = generate_perfume_aliases("Parfums de Marly", "Layton Eau de Parfum")
        assert "parfums de marly layton" in aliases
        assert "pdm layton" in aliases
        # Bare 1-token base excluded
        assert "layton" not in aliases

    def test_long_alias_still_present(self):
        """Short alias must not replace the long-form alias."""
        aliases = generate_perfume_aliases("Serge Lutens", "Ambre Sultan Eau de Parfum")
        assert "serge lutens ambre sultan eau de parfum" in aliases
        assert "ambre sultan eau de parfum" in aliases

    def test_no_suffix_name_unchanged(self):
        """Perfume without concentration suffix: no extra aliases, no breakage."""
        aliases_with = generate_perfume_aliases("Dior", "Sauvage")
        # No new short aliases added (already short)
        assert "sauvage" in aliases_with
        assert "dior sauvage" in aliases_with

    def test_baccarat_rouge_stripped_alias(self):
        aliases = generate_perfume_aliases(
            "Maison Francis Kurkdjian", "Baccarat Rouge 540 Extrait de Parfum"
        )
        assert "baccarat rouge 540" in aliases
        assert "mfk baccarat rouge 540" in aliases

    def test_aliases_are_lowercase_normalized(self):
        aliases = generate_perfume_aliases("Diptyque", "Philosykos - Eau de Parfum")
        for a in aliases:
            assert a == a.lower(), f"Alias not lowercase: {a!r}"

    def test_aliases_deterministic(self):
        """Same input always produces identical sorted alias list."""
        a1 = generate_perfume_aliases("Serge Lutens", "Ambre Sultan Eau de Parfum")
        a2 = generate_perfume_aliases("Serge Lutens", "Ambre Sultan Eau de Parfum")
        assert a1 == a2


# ---------------------------------------------------------------------------
# Cross-brand collision safety
# ---------------------------------------------------------------------------

class TestCollisionSafety:
    def test_two_brands_same_stripped_base_use_brand_prefixed_aliases(self, resolver):
        """Bare 1-token stripped base 'rose' is NOT added (false-positive guard).
        Brand-prefixed aliases 'diptyque rose' and 'byredo rose' ARE added,
        keeping both entities resolvable without ambiguity."""
        import sqlite3
        conn = sqlite3.connect(resolver.store.db_path)

        # Bare 'rose' must not exist as a perfume alias (would be ambiguous)
        bare_rows = conn.execute(
            "SELECT entity_id FROM aliases WHERE normalized_alias_text = 'rose' AND entity_type = 'perfume'"
        ).fetchall()
        assert len(bare_rows) == 0, (
            f"Bare 'rose' alias should not exist; found {len(bare_rows)} row(s)"
        )

        # Brand-prefixed aliases must exist for both entities
        for brand_alias in ("diptyque rose", "byredo rose"):
            rows = conn.execute(
                "SELECT entity_id FROM aliases WHERE normalized_alias_text = ? AND entity_type = 'perfume'",
                (brand_alias,),
            ).fetchall()
            assert len(rows) == 1, (
                f"Expected 1 row for {brand_alias!r}, found {len(rows)}"
            )
        conn.close()

    def test_specific_short_alias_resolves_to_correct_entity(self, resolver):
        """Brand-prefixed short aliases are unambiguous even when the stripped
        base is shared: 'diptyque philosykos' → Diptyque, not Serge Lutens."""
        result = resolver.resolve_content_item({
            "id": "t1",
            "text_content": "I love diptyque philosykos",
        })
        names = [e["canonical_name"] for e in result["resolved_entities"]]
        assert any("Philosykos" in n for n in names)
        assert not any("Ambre" in n for n in names)

    def test_aventus_does_not_resolve_to_wrong_entity(self, resolver):
        """'aventus' must resolve to Creed Aventus only."""
        result = resolver.resolve_content_item({
            "id": "t2",
            "text_content": "aventus is a masterpiece",
        })
        names = [e["canonical_name"] for e in result["resolved_entities"]]
        assert any("Aventus" in n for n in names)
        assert len(set(n for n in names if "Aventus" in n)) == 1, (
            f"'aventus' resolved to multiple entities: {names}"
        )


# ---------------------------------------------------------------------------
# End-to-end resolver: short mentions resolve
# ---------------------------------------------------------------------------

class TestShortMentionResolution:
    def test_ambre_sultan_resolves(self, resolver):
        result = resolver.resolve_content_item({
            "id": "t1",
            "text_content": "My first Serge Lutens purchase. Ambre Sultan review!",
        })
        names = [e["canonical_name"] for e in result["resolved_entities"]]
        assert any("Ambre Sultan" in n for n in names), (
            f"'Ambre Sultan' not resolved; got: {names}"
        )

    def test_philosykos_resolves(self, resolver):
        result = resolver.resolve_content_item({
            "id": "t2",
            "text_content": "Diptyque Philosykos EDT longevity?",
        })
        names = [e["canonical_name"] for e in result["resolved_entities"]]
        assert any("Philosykos" in n for n in names), (
            f"'Philosykos' not resolved; got: {names}"
        )

    def test_layton_resolves_via_brand_prefix(self, resolver):
        """Bare 'layton' (1-token) is not a standalone alias (false-positive guard).
        Brand-prefixed 'parfums de marly layton' / 'pdm layton' resolve correctly."""
        # Full brand-prefixed mention resolves
        result = resolver.resolve_content_item({
            "id": "t3a",
            "text_content": "Looking for a pdm layton dupe",
        })
        names = [e["canonical_name"] for e in result["resolved_entities"]]
        assert any("Layton" in n for n in names), (
            f"'pdm layton' not resolved; got: {names}"
        )

        # Bare 'layton' alone does NOT resolve (by design — 1-token guard)
        result2 = resolver.resolve_content_item({
            "id": "t3b",
            "text_content": "Looking for a Layton dupe",
        })
        names2 = [e["canonical_name"] for e in result2["resolved_entities"]]
        assert not any("Layton" in n for n in names2), (
            "Bare 'layton' resolved unexpectedly — 1-token guard may be broken"
        )

    def test_baccarat_rouge_540_short_resolves(self, resolver):
        result = resolver.resolve_content_item({
            "id": "t4",
            "text_content": "Is Baccarat Rouge 540 worth it?",
        })
        names = [e["canonical_name"] for e in result["resolved_entities"]]
        assert any("Baccarat Rouge 540" in n for n in names)

    def test_canonical_data_not_changed(self, resolver):
        """Canonical names in fragrance_master must be unchanged by alias rebuild."""
        import sqlite3
        conn = sqlite3.connect(resolver.store.db_path)
        row = conn.execute(
            "SELECT canonical_name FROM perfumes WHERE canonical_name LIKE '%Ambre Sultan%'"
        ).fetchone()
        conn.close()
        assert row is not None
        # canonical name preserves original casing / concentration term
        assert "Ambre Sultan" in row[0]
