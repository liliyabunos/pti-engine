"""Phase I7.5 — Entity Role Classification.

Deterministic classification of a fragrance entity's market role based on its
brand name. No AI, no database calls — pure lookup against curated brand lists.

Roles:
  designer_original  — major designer house (Dior, Chanel, Armani, …)
  niche_original     — independent/niche house (Creed, MFK, Parfums de Marly, …)
  original           — known original, house tier not yet categorised
  clone_positioned   — entity explicitly positioned as a dupe/clone (Phase 3)
  inspired_alternative — lighter clone signal (Phase 3)
  flanker            — line extension of an existing entity (Phase 3)
  unknown            — insufficient signal to classify

Phase 2 covers: designer_original, niche_original, unknown.
clone_positioned, inspired_alternative, flanker classification deferred to Phase 3.

Safety note:
  This module assigns roles based on house affiliation only.
  It makes no counterfeit or infringement claims.
  "clone_positioned" and "inspired_alternative" are market-intelligence
  descriptions of community/search framing, not legal judgements.
"""
from __future__ import annotations

import re
import unicodedata

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
    "donna konna",
    "donna karan",
    "dkny",
    "nina ricci",
    "rochas",
    "cacharel",
    "jil sander",
    "davidoff",
    "dunhill",
    "azzaro",
    "eau de rochas",
    "lanvin",
    "balmain",
    "lolita lempicka",
    "escada",
    "hugo",
})

# Independent / niche fragrance houses.
# These produce reference-tier scents in the premium/ultra-premium segment.
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
    "four pillars",
    "gris dior",
    "parfums christian dior",
    "jolly roger",
    "jovoy",
    "fragrance du bois",
    "ensar oud",
    "rasasi",
    "swiss arabian",
    "ajmal",
    "al haramain",
    "lattafa",
    "armaf",
    "afnan",
    "zimaya",
    "fragrance world",
    "oud elite",
    "orientica",
    "arabiyat",
    "ard al zaafaran",
    "parfums de nicolai",
    "liquides imaginaires",
    "house of oud",
    "the different company",
    "evody",
    "boadicea the victorious",
    "henry rose",
    "imaginary authors",
    "sweet tea apothecary",
    "commodity",
    "zoologist",
    "sweet dreams",
    "nez a nez",
    "profumum roma",
    "dr vranjes",
    "santa maria novella",
    "etro",
    "acqua di parma",
    "santa maria novella firenze",
    "borsari",
    "carthusia",
    "filippo sorcinelli",
    "andrea maack",
    "olfactive studio",
    "theodoros kalotinis",
    "monocle x comme des garcons",
    "monocle",
    "gres",
    "grès",
    "meo fusciuni",
    "unum",
    "antonio alessandria",
    "nobile 1942",
    "mendittorosa",
    "masque milano",
    "berto",
    "filippo stanzani",
    "parfumerie generale",
    "smell bent",
    "the merchant of venice",
    "bloom perfumery",
    "eight & bob",
    "os fragrances",
    "liquides imaginaires",
    "ralf lauren",
    "jovoy paris",
    "papillon",
    "puredistance",
    "floraiku",
    "rance 1795",
    "sweet chemistry",
    "bogue profumo",
    "the parfumerie",
    "in fiore",
    "ineke",
    "james heeley",
    "heeley",
    "olibere parfums",
    "bvlgari le gemme",
    "roja",
    "vilhelm",
    "frederic",
    "parfums de marly paris",
    "maison de la sixtine",
    "house of matriarch",
    "mcq",
    "shay & blue",
    "cire trudon",
    "goldfield & banks",
    "noble isle",
    "frama",
    "fueguia 1833",
    "filippo",
    "the zoo project",
    "le jardin retrouve",
    "the house of oud",
    "olfactif",
    "scentbird exclusive",
    "elie saab",
    "viktor rolf",
    "givenchy le de",
    "jo malone",
    "jo malone london",
    "penhaligon",
    "parfums lalique",
    "lalique",
    "s.t. dupont",
    "dupont",
    "serge",
    "parfums lutens",
    "talitha",
    "perris monte carlo",
    "roos & roos",
    "floris",
    "czech & speake",
    "james heelay",
    "molinard",
    "officine universelle buly",
    "buly 1803",
    "grandiflora",
    "ormonde jayne",
    "house of fraser",
    "nicolas kristiante",
    "ds durga",
    "kerosene",
    "yosh han",
    "sonoma scent studio",
    "house of sillage",
    "clive christian",
    "boadicea",
    "xerjoff naxos",
    "roja dove parfums",
    "the vagabond prince",
    "fume hood",
    "mona di orio",
    "robert piguet",
    "jm",
    "jo malone london",
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_entity_role(
    brand_name: str | None,
    perfume_name: str | None = None,  # reserved for Phase 3 name-level signals
) -> str:
    """Classify the entity's market role from its brand name.

    Args:
        brand_name:   The brand/house name (e.g. "Creed", "Dior").
        perfume_name: Reserved for future use (Phase 3 name-level classification).
                      Currently unused.

    Returns:
        One of: "designer_original" | "niche_original" | "original" |
                "clone_positioned" | "inspired_alternative" | "flanker" | "unknown"

    Phase 2 scope: only "designer_original", "niche_original", "unknown" are assigned.
    The remaining roles are reserved for Phase 3.
    """
    if not brand_name:
        return "unknown"

    key = _normalize(brand_name)
    if not key:
        return "unknown"

    if key in _DESIGNER_NORM:
        return "designer_original"

    if key in _NICHE_NORM:
        return "niche_original"

    # Phase 3 will add clone_positioned / inspired_alternative / flanker signals here.
    return "unknown"


# Human-readable labels for the frontend.
ROLE_LABELS: dict[str, str] = {
    "designer_original":   "Designer Original",
    "niche_original":      "Niche Original",
    "original":            "Original",
    "clone_positioned":    "Clone-Positioned",
    "inspired_alternative": "Inspired Alternative",
    "flanker":             "Flanker",
    "unknown":             "",  # not rendered in UI
}

# Roles that should be rendered in the UI (unknown suppressed).
RENDERABLE_ROLES: frozenset[str] = frozenset(ROLE_LABELS) - {"unknown"}
