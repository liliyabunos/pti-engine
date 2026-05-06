"""Phase I7.5 — Entity Role Classification.

Deterministic classification of a fragrance entity's market role based on its
brand name and (Phase 5) canonical perfume name. No AI, no database calls —
pure lookup against curated brand lists and dupe mapping.

Roles:
  designer_original      — major designer house (Dior, Chanel, Armani, …)
  niche_original         — independent/niche house (Creed, MFK, Parfums de Marly, …)
  original               — known original, house tier not yet categorised
  dupe_alternative       — known clone/dupe of a specific reference original
                           (e.g. Armaf CDNIM → Creed Aventus)
  designer_alternative   — designer house product positioned as similar to a niche ref
                           (e.g. Montblanc Explorer → Creed Aventus)
  celebrity_alternative  — celebrity-brand product positioned near a niche ref
                           (e.g. Ariana Grande Cloud → MFK Baccarat Rouge 540)
  clone_positioned       — entity explicitly positioned as a dupe/clone (Phase 3 generic)
  inspired_alternative   — lighter clone signal (Phase 3 generic)
  flanker                — line extension of an existing entity
  unknown                — insufficient signal to classify

Phase 2: designer_original, niche_original, unknown from brand lookup.
Phase 5: dupe_alternative, designer_alternative, celebrity_alternative from dupe map.
Phase 3 generic roles (clone_positioned, inspired_alternative, flanker) deferred.

Safety note:
  This module assigns roles based on house affiliation and curated community knowledge.
  It makes no counterfeit or infringement claims.
  "dupe_alternative" and related roles are market-intelligence descriptions of
  community/search framing, not legal judgements.
"""
from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple, Optional

# ---------------------------------------------------------------------------
# Dupe profile type (Phase 5)
# ---------------------------------------------------------------------------

class DupeProfile(NamedTuple):
    """Market positioning data for a known alternative/dupe entity."""
    role: str                  # "dupe_alternative" | "designer_alternative" | "celebrity_alternative"
    reference_original: str    # canonical name of the reference scent, e.g. "Creed Aventus"
    dupe_family: str           # grouping label, e.g. "Aventus alternatives"


# ---------------------------------------------------------------------------
# Dupe / alternative mapping (Phase 5)
#
# Keys: normalized canonical perfume name (full name including brand).
# Values: DupeProfile
#
# Add entries conservatively — only include well-established community consensus.
# ---------------------------------------------------------------------------

_DUPE_RAW: dict[str, DupeProfile] = {
    # ── Creed Aventus alternatives ──────────────────────────────────────────
    "Armaf Club de Nuit Intense Man": DupeProfile(
        "dupe_alternative", "Creed Aventus", "Aventus alternatives"
    ),
    "Armaf Club de Nuit Intense": DupeProfile(
        "dupe_alternative", "Creed Aventus", "Aventus alternatives"
    ),
    "Club de Nuit Intense Man": DupeProfile(
        "dupe_alternative", "Creed Aventus", "Aventus alternatives"
    ),
    # Common abbreviations / short forms as stored in resolver
    "CDNIM": DupeProfile(
        "dupe_alternative", "Creed Aventus", "Aventus alternatives"
    ),
    "Armaf CDNIM": DupeProfile(
        "dupe_alternative", "Creed Aventus", "Aventus alternatives"
    ),
    # Designer alternative
    "Montblanc Explorer": DupeProfile(
        "designer_alternative", "Creed Aventus", "Aventus alternatives"
    ),
    # ── Maison Francis Kurkdjian Baccarat Rouge 540 alternatives ────────────
    "Lattafa Khamrah": DupeProfile(
        "dupe_alternative",
        "Maison Francis Kurkdjian Baccarat Rouge 540",
        "BR540 alternatives",
    ),
    "Zara Red Temptation": DupeProfile(
        "dupe_alternative",
        "Maison Francis Kurkdjian Baccarat Rouge 540",
        "BR540 alternatives",
    ),
    "Ariana Grande Cloud": DupeProfile(
        "celebrity_alternative",
        "Maison Francis Kurkdjian Baccarat Rouge 540",
        "BR540 alternatives",
    ),
    # ── Kilian Angels' Share alternatives ───────────────────────────────────
    "Lattafa Khamrah Qahwa": DupeProfile(
        "dupe_alternative",
        "Kilian Angels' Share",
        "Angels' Share alternatives",
    ),
}


# ---------------------------------------------------------------------------
# Brand lists
# ---------------------------------------------------------------------------

# Major designer / luxury conglomerate houses.
# These produce reference-tier, widely-copied fragrances.
_DESIGNER_ORIGINALS: frozenset[str] = frozenset({
    "dior",
    "christian dior",
    "chanel",
    "yves saint laurent",
    "ysl",
    "givenchy",
    "gucci",
    "prada",
    "giorgio armani",
    "armani",
    "versace",
    "gianni versace",
    "burberry",
    "hugo boss",
    "boss",
    "tom ford",
    "valentino",
    "hermes",
    "hermès",
    "cartier",
    "montblanc",
    "jean paul gaultier",
    "dolce & gabbana",
    "dolce and gabbana",
    "d&g",
    "paco rabanne",
    "rabanne",
    "viktor & rolf",
    "viktor&rolf",
    "carolina herrera",
    "mugler",
    "thierry mugler",
    "calvin klein",
    "ralph lauren",
    "polo ralph lauren",
    "lancome",
    "lancôme",
    "ysl beaute",
    "l'oreal",
    "loreal",
    "chloe",
    "chloé",
    "loewe",
    "salvatore ferragamo",
    "ferragamo",
    "trussardi",
    "bvlgari",
    "bulgari",
    "lacoste",
    "mont blanc",
    "givenchy parfums",
    "issey miyake",
    "kenzo",
    "coach",
    "michael kors",
    "marc jacobs",
    "donna karan",
    "dkny",
    "nina ricci",
    "rochas",
    "cacharel",
    "jil sander",
    "davidoff",
    "dunhill",
    "azzaro",
    "lanvin",
    "balmain",
    "lolita lempicka",
    "escada",
    "hugo",
})

# Independent / niche fragrance houses.
# These produce reference-tier scents in the premium/ultra-premium segment.
#
# Phase 5 note: mass-market affordable brands (Armaf, Lattafa, Zimaya, etc.)
# have been removed. These are clone/affordable brands, not niche originals.
# Specific products from those brands are handled via _DUPE_RAW above.
_NICHE_ORIGINALS: frozenset[str] = frozenset({
    "creed",
    "house of creed",
    "maison francis kurkdjian",
    "francis kurkdjian",
    "mfk",
    "parfums de marly",
    "xerjoff",
    "roja parfums",
    "roja dove",
    "amouage",
    "initio",
    "initio parfums prives",
    "initio parfums privés",
    "nishane",
    "byredo",
    "le labo",
    "diptyque",
    "memo paris",
    "memo",
    "serge lutens",
    "frederic malle",
    "frédéric malle",
    "editions de parfums frederic malle",
    "penhaligons",
    "penhaligon's",
    "clive christian",
    "orto parisi",
    "tiziana terenzi",
    "kilian",
    "by kilian",
    "bdk parfums",
    "ex nihilo",
    "mancera",
    "montale",
    "maison crivelli",
    "vilhelm parfumerie",
    "juliette has a gun",
    "etat libre d'orange",
    "etat libre dorange",
    "nasomatto",
    "parfum de la bastide",
    "histoires de parfums",
    "l'artisan parfumeur",
    "artisan parfumeur",
    "annick goutal",
    "goutal paris",
    "atelier cologne",
    "maison martin margiela",
    "replica",
    "margiela",
    "maison margiela",
    "comme des garcons",
    "comme des garçons",
    "cdg",
    "papillon artisan perfumes",
    "beaufort london",
    "d.s. & durga",
    "ds & durga",
    "fragrance du bois",
    "ensar oud",
    "rasasi",
    "swiss arabian",
    "ajmal",
    "al haramain",
    "parfums de nicolai",
    "liquides imaginaires",
    "house of oud",
    "the different company",
    "evody",
    "boadicea the victorious",
    "henry rose",
    "imaginary authors",
    "commodity",
    "zoologist",
    "profumum roma",
    "santa maria novella",
    "etro",
    "acqua di parma",
    "carthusia",
    "filippo sorcinelli",
    "andrea maack",
    "olfactive studio",
    "theodoros kalotinis",
    "gres",
    "grès",
    "meo fusciuni",
    "unum",
    "antonio alessandria",
    "nobile 1942",
    "mendittorosa",
    "masque milano",
    "parfumerie generale",
    "the merchant of venice",
    "eight & bob",
    "jovoy",
    "jovoy paris",
    "papillon",
    "puredistance",
    "floraiku",
    "rance 1795",
    "bogue profumo",
    "ineke",
    "james heeley",
    "heeley",
    "roja",
    "vilhelm",
    "parfums de marly paris",
    "maison de la sixtine",
    "house of matriarch",
    "shay & blue",
    "cire trudon",
    "goldfield & banks",
    "noble isle",
    "fueguia 1833",
    "le jardin retrouve",
    "the house of oud",
    "elie saab",
    "jo malone",
    "jo malone london",
    "penhaligon",
    "parfums lalique",
    "lalique",
    "s.t. dupont",
    "dupont",
    "parfums lutens",
    "perris monte carlo",
    "floris",
    "czech & speake",
    "molinard",
    "officine universelle buly",
    "buly 1803",
    "ormonde jayne",
    "kerosene",
    "house of sillage",
    "boadicea",
    "xerjoff naxos",
    "roja dove parfums",
    "mona di orio",
    "robert piguet",
    "jm",
})


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"['\u2019&.,;:!?]")
_MULTI_WS = re.compile(r"\s+")


def _normalize(name: str) -> str:
    """Lowercase, strip accents where practical, collapse whitespace, remove light punctuation."""
    # NFD decompose to separate base chars from combining marks
    nfd = unicodedata.normalize("NFD", name)
    # Strip combining marks (accents) — keeps base ASCII letters
    stripped = "".join(c for c in nfd if not unicodedata.combining(c))
    lower = stripped.lower()
    # Remove light punctuation (apostrophes, ampersands, etc.)
    no_punct = _PUNCT_RE.sub(" ", lower)
    # Collapse whitespace
    return _MULTI_WS.sub(" ", no_punct).strip()


# Pre-compute normalized lookup sets for O(1) membership.
_DESIGNER_NORM: frozenset[str] = frozenset(_normalize(b) for b in _DESIGNER_ORIGINALS)
_NICHE_NORM: frozenset[str] = frozenset(_normalize(b) for b in _NICHE_ORIGINALS)

# Pre-compute normalized dupe map.
_DUPE_NORM: dict[str, DupeProfile] = {
    _normalize(k): v for k, v in _DUPE_RAW.items()
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_dupe_profile(
    brand_name: str | None,
    canonical_name: str | None,
) -> Optional[DupeProfile]:
    """Return the DupeProfile if this entity is a known dupe/alternative, else None.

    Checks the canonical_name (full entity name including brand) against the
    curated dupe map. Brand-only lookup is intentionally NOT performed — dupe
    status is perfume-specific, not brand-wide.

    Args:
        brand_name:     Brand name (not used for lookup; reserved for future use).
        canonical_name: Full canonical entity name, e.g. "Armaf Club de Nuit Intense Man".

    Returns:
        DupeProfile if found, else None.
    """
    if not canonical_name:
        return None
    key = _normalize(canonical_name)
    return _DUPE_NORM.get(key)


def classify_entity_role(
    brand_name: str | None,
    perfume_name: str | None = None,
) -> str:
    """Classify the entity's market role from its brand name and canonical perfume name.

    Lookup order (Phase 5):
      1. Dupe map — keyed by normalized canonical perfume name (most specific)
      2. Designer brand set — keyed by normalized brand name
      3. Niche brand set    — keyed by normalized brand name
      4. Fallback           — "unknown"

    Args:
        brand_name:   The brand/house name (e.g. "Creed", "Armaf").
        perfume_name: Full canonical entity name (e.g. "Armaf Club de Nuit Intense Man").
                      Required for dupe map lookup; previously reserved for Phase 3.

    Returns:
        One of: "designer_original" | "niche_original" | "original" |
                "dupe_alternative" | "designer_alternative" | "celebrity_alternative" |
                "clone_positioned" | "inspired_alternative" | "flanker" | "unknown"
    """
    # 1. Dupe map check — requires canonical perfume name
    if perfume_name:
        profile = get_dupe_profile(brand_name, perfume_name)
        if profile:
            return profile.role

    # 2–3. Brand-level lookup
    if not brand_name:
        return "unknown"

    key = _normalize(brand_name)
    if not key:
        return "unknown"

    if key in _DESIGNER_NORM:
        return "designer_original"

    if key in _NICHE_NORM:
        return "niche_original"

    # Phase 3/4 will add clone_positioned / inspired_alternative / flanker here.
    return "unknown"


# Human-readable labels for the frontend.
ROLE_LABELS: dict[str, str] = {
    "designer_original":     "Designer Original",
    "niche_original":        "Niche Original",
    "original":              "Original",
    "dupe_alternative":      "Dupe / Alternative",
    "designer_alternative":  "Designer Alternative",
    "celebrity_alternative": "Celebrity Alternative",
    "clone_positioned":      "Clone-Positioned",
    "inspired_alternative":  "Inspired Alternative",
    "flanker":               "Flanker",
    "unknown":               "",  # not rendered in UI
}

# Roles that should be rendered in the UI (unknown suppressed).
RENDERABLE_ROLES: frozenset[str] = frozenset(ROLE_LABELS) - {"unknown"}
