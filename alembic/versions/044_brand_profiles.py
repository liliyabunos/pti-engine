"""FTG-1/KB1-MIN — brand_profiles canonical classification table

Revision ID: 044
Revises: 043
Create Date: 2026-05-14

Fragrance Truth Graph phase 1 — minimal canonical brand classification.

Creates brand_profiles: a thin operator-curated table holding brand tier
classification. This is the first step in moving brand role knowledge out of
hardcoded Python frozensets (_DESIGNER_ORIGINALS, _NICHE_ORIGINALS in entity_role.py)
into queryable, versionable data.

Intentionally minimal:
  - brand_name_normalized TEXT UNIQUE  — pre-normalized lookup key
  - brand_tier VARCHAR(32)             — designer | niche | clone_house | celebrity | indie
  - notes TEXT NULL                    — optional operator annotation
  - created_at                         — for audit

Explicitly out of scope:
  - founded year, country, current owner, house style, reformulation history
  - perfumer credits, discontinued status
  - any relationship tables (those are FTG-2/RI1)

Seeds from hardcoded frozensets in entity_role.py:
  - _DESIGNER_ORIGINALS  → brand_tier = 'designer'
  - _NICHE_ORIGINALS     → brand_tier = 'niche'
  - small clone_house set (brands removed from _NICHE_ORIGINALS at Semantic Phase 5)
  - one celebrity brand from dupe map

Normalization (mirrored from entity_role._normalize()):
  NFD decompose → strip combining marks → lowercase →
  remove ['\u2019&.,;:!?] → collapse whitespace
This matches the lookup path in classify_entity_role() exactly.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List, Tuple

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Normalization — mirrors entity_role._normalize() exactly
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"['\u2019&.,;:!?]")
_MULTI_WS = re.compile(r"\s+")


def _norm(name: str) -> str:
    nfd = unicodedata.normalize("NFD", name)
    stripped = "".join(c for c in nfd if not unicodedata.combining(c))
    lower = stripped.lower()
    no_punct = _PUNCT_RE.sub(" ", lower)
    return _MULTI_WS.sub(" ", no_punct).strip()


# ---------------------------------------------------------------------------
# Seed data — migrated from hardcoded Python frozensets
# ---------------------------------------------------------------------------

_DESIGNER_RAW = [
    "dior", "christian dior", "chanel", "yves saint laurent", "ysl",
    "givenchy", "gucci", "prada", "giorgio armani", "armani", "versace",
    "gianni versace", "burberry", "hugo boss", "boss", "tom ford",
    "valentino", "hermes", "hermès", "cartier", "montblanc",
    "jean paul gaultier", "dolce & gabbana", "dolce and gabbana", "d&g",
    "paco rabanne", "rabanne", "viktor & rolf", "viktor&rolf",
    "carolina herrera", "mugler", "thierry mugler", "calvin klein",
    "ralph lauren", "polo ralph lauren", "lancome", "lancôme",
    "ysl beaute", "l'oreal", "loreal", "chloe", "chloé", "loewe",
    "salvatore ferragamo", "ferragamo", "trussardi", "bvlgari", "bulgari",
    "lacoste", "mont blanc", "givenchy parfums", "issey miyake", "kenzo",
    "coach", "michael kors", "marc jacobs", "donna karan", "dkny",
    "nina ricci", "rochas", "cacharel", "jil sander", "davidoff",
    "dunhill", "azzaro", "lanvin", "balmain", "lolita lempicka",
    "escada", "hugo",
]

_NICHE_RAW = [
    "creed", "house of creed", "maison francis kurkdjian",
    "francis kurkdjian", "mfk", "parfums de marly", "xerjoff",
    "roja parfums", "roja dove", "amouage", "initio",
    "initio parfums prives", "initio parfums privés", "nishane", "byredo",
    "le labo", "diptyque", "memo paris", "memo", "serge lutens",
    "frederic malle", "frédéric malle",
    "editions de parfums frederic malle", "penhaligons", "penhaligon's",
    "clive christian", "orto parisi", "tiziana terenzi", "kilian",
    "by kilian", "bdk parfums", "ex nihilo", "mancera", "montale",
    "maison crivelli", "vilhelm parfumerie", "juliette has a gun",
    "etat libre d'orange", "etat libre dorange", "nasomatto",
    "parfum de la bastide", "histoires de parfums", "l'artisan parfumeur",
    "artisan parfumeur", "annick goutal", "goutal paris", "atelier cologne",
    "maison martin margiela", "replica", "margiela", "maison margiela",
    "comme des garcons", "comme des garçons", "cdg",
    "papillon artisan perfumes", "beaufort london", "d.s. & durga",
    "ds & durga", "fragrance du bois", "ensar oud", "rasasi",
    "swiss arabian", "ajmal", "al haramain", "parfums de nicolai",
    "liquides imaginaires", "house of oud", "the different company",
    "evody", "boadicea the victorious", "henry rose", "imaginary authors",
    "commodity", "zoologist", "profumum roma", "santa maria novella",
    "etro", "acqua di parma", "carthusia", "filippo sorcinelli",
    "andrea maack", "olfactive studio", "theodoros kalotinis", "gres",
    "grès", "meo fusciuni", "unum", "antonio alessandria", "nobile 1942",
    "mendittorosa", "masque milano", "parfumerie generale",
    "the merchant of venice", "eight & bob", "jovoy", "jovoy paris",
    "papillon", "puredistance", "floraiku", "rance 1795", "bogue profumo",
    "ineke", "james heeley", "heeley", "roja", "vilhelm",
    "parfums de marly paris", "maison de la sixtine", "house of matriarch",
    "shay & blue", "cire trudon", "goldfield & banks", "noble isle",
    "fueguia 1833", "le jardin retrouve", "the house of oud", "elie saab",
    "jo malone", "jo malone london", "penhaligon", "parfums lalique",
    "lalique", "s.t. dupont", "dupont", "parfums lutens",
    "perris monte carlo", "floris", "czech & speake", "molinard",
    "officine universelle buly", "buly 1803", "ormonde jayne", "kerosene",
    "house of sillage", "boadicea", "xerjoff naxos", "roja dove parfums",
    "mona di orio", "robert piguet", "jm",
]

# Brands removed from _NICHE_ORIGINALS at Semantic Phase 5 (mass-market clone/affordable brands)
# + common clone houses used in dupe community
_CLONE_HOUSE_RAW = [
    "armaf", "lattafa", "zimaya", "fragrance world", "orientica",
    "arabiyat", "ard al zaafaran", "afnan", "alexandria fragrances",
]

# Celebrity brands currently in dupe map
_CELEBRITY_RAW = [
    "ariana grande",
    "zara",   # fast-fashion house with frag line; primarily known for Zara Red Temptation BR540 dupe
]


def _build_rows() -> List[Tuple[str, str]]:
    """Return (brand_name_normalized, brand_tier) tuples, deduplicated."""
    seen: set[str] = set()
    rows: List[Tuple[str, str]] = []

    def _add(names: List[str], tier: str) -> None:
        for raw in names:
            key = _norm(raw)
            if key and key not in seen:
                seen.add(key)
                rows.append((key, tier))

    _add(_DESIGNER_RAW, "designer")
    _add(_NICHE_RAW, "niche")
    _add(_CLONE_HOUSE_RAW, "clone_house")
    _add(_CELEBRITY_RAW, "celebrity")
    return rows


def upgrade() -> None:
    op.create_table(
        "brand_profiles",
        sa.Column("id", PG_UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"),
                  nullable=False, primary_key=True),
        sa.Column("brand_name_normalized", sa.Text(), nullable=False),
        sa.Column("brand_tier", sa.String(32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("brand_name_normalized", name="uq_brand_profiles_normalized"),
    )
    op.create_index(
        "ix_brand_profiles_brand_name_normalized",
        "brand_profiles",
        ["brand_name_normalized"],
    )

    # Seed
    rows = _build_rows()
    if rows:
        conn = op.get_bind()
        conn.execute(
            sa.text(
                "INSERT INTO brand_profiles (brand_name_normalized, brand_tier) "
                "VALUES (:n, :t) "
                "ON CONFLICT (brand_name_normalized) DO NOTHING"
            ),
            [{"n": n, "t": t} for n, t in rows],
        )


def downgrade() -> None:
    op.drop_index("ix_brand_profiles_brand_name_normalized", table_name="brand_profiles")
    op.drop_table("brand_profiles")
