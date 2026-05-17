from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from perfume_trend_sdk.utils.alias_generator import normalize_text
from perfume_trend_sdk.storage.entities.fragrance_master_store import FragranceMasterStore

_log = logging.getLogger(__name__)

# Maximum token window for alias sliding-window matching.
# Raised from 4 → 6 to cover aliases such as:
#   "diptyque philosykos eau de parfum"   (5 tokens)
#   "serge lutens ambre sultan eau de parfum" (6 tokens)
_MAX_WINDOW = 6

# Minimum token length to consider a phrase as an unresolved candidate.
# Single-word generic tokens ("perfume", "cologne", "scent") are suppressed.
_MIN_CANDIDATE_TOKENS = 2

_GENERIC_TOKENS: frozenset[str] = frozenset({
    "perfume", "cologne", "scent", "fragrance", "smell", "note",
    "edt", "edp", "eau de parfum", "eau de toilette",
    "parfum", "extrait",
})

# ---------------------------------------------------------------------------
# Single-word alias safety guards
# ---------------------------------------------------------------------------

# Tokens that look like they follow a contraction apostrophe after normalize_text()
# strips the apostrophe to a space.
#   "don't"  → ["don", "t"]
#   "can't"  → ["can", "t"]
#   "they're" → ["they", "re"]
#   "it's"   → ["it", "s"]    (note: "'s" is removed by normalize_text first,
#                               but "it's" → "it" only via the 's regex)
# A single-word alias match followed immediately by one of these tail tokens is
# almost certainly a contraction artifact, not a real entity mention.
_CONTRACTION_TAILS: frozenset[str] = frozenset({
    "t", "nt", "s", "ll", "re", "ve", "d", "m",
})

# Single-word alias strings that are too short or too generic to be matched
# safely in free-form social text (titles, hashtags, captions).
# These words appear as standalone alias entries in resolver_aliases but are
# common English words — matching them produces too many false positives.
#
# Rule: when the sliding window size == 1, the matched phrase must NOT be in
# this set.  Multi-token aliases (size ≥ 2) are unaffected — "join the club don"
# or "armaf club de nuit" are specific enough to match safely.
_BLOCKED_SINGLE_WORD_ALIASES: frozenset[str] = frozenset({
    # Perfume names that are common English words / contractions
    "don",      # Xerjoff Join the Club Don — "don't" → ["don", "t"]
    "pink",     # Nanadebary Pink — "Pink eye" / "#cologne #pink" unrelated titles
    "dot",      # Marc Jacobs Dot — too generic
    "smart",    # various — too generic
    "standard", # various — too generic
    "heritage", # various — too generic
    "moth",     # various — too generic
    "jack",     # various — too generic
    "man",      # various — too generic
    "two",      # Knize Two Eau de Toilette — "I bought two frags", "these two scents"
    # Numeric short aliases (conflict with URLs, prices, ratings in titles)
    "11",       # Boris Bidjan Saberi 11
    "21",       # Costume National 21
})

# ---------------------------------------------------------------------------
# Blocked multi-token phrases (RES-AMB3)
# ---------------------------------------------------------------------------
#
# Phrases of 2+ tokens that are unconditionally blocked because:
#  (a) the phrase is a common evaluative/conversational expression, AND
#  (b) the brand token(s) are too short/generic to be usable as proximity
#      anchors in _AMBIGUOUS_PHRASE_GUARD.
#
# Unlike _AMBIGUOUS_PHRASE_GUARD (which requires brand proximity), these
# phrases are blocked regardless of surrounding context.  Use this set only
# when the brand name itself is a common word (e.g. "so", "first") that would
# generate false positives if used as a proximity anchor.
#
# RES-AMB3 (2026-05-17):
#   "so so"  → So...? So...? (brand: So...?) — normalize_text("So...? So...?")
#              → "so so"; "so" is a common adverb; no usable brand anchor.
#              Fired on generic evaluative usage: "it was so so disappointing".
#
_BLOCKED_MULTI_TOKEN_PHRASES: frozenset[str] = frozenset({
    "so so",        # So...? So...? (brand=So...?) — "so so" = common evaluative phrase; brand "so" too generic
    "i am so so",   # I Am So...? So...? (brand=So...?) — "i am so so" = common intensifier phrase
    "so i am so so",  # variant alias for same entity
})

# ---------------------------------------------------------------------------
# Ambiguous multi-token phrase guard (RES-AMB1 / RES-AMB2 / RES-AMB3)
# ---------------------------------------------------------------------------
#
# Some 2–3-token aliases are common English phrases that happen to match a
# perfume name.  For these, a match is allowed ONLY when at least one brand
# token from the corresponding brand_token_set appears within ±10 tokens of
# the match position in the same text window.
#
# Structure:
#   normalized_alias → [frozenset_of_brand_tokens, ...]
#
# A phrase is allowed if at least one brand token from ANY of the listed sets
# appears in the surrounding context window.
#
# RES-AMB1 seed (2026-05-16 — founder-confirmed false-positive entities):
#   "i am"       → I Am Juicy Couture     (brand: Juicy Couture)
#   "right now"  → Right Now West Third Brand (brand: West Third Brand)
#   "scent of"   → Scent of Liu·Jo        (brand: Liu·Jo → "liu jo" normalized)
#   "blue oud"   → Blue Oud Ajwaa Perfumes (brand: Ajwaa Perfumes)
#   "peace love" → Peace, Love & Juicy Couture (brand: Juicy Couture)
#
# RES-AMB2 expansion (2026-05-16 — audit-confirmed false-positive entities):
#   "so you"              → So You (Alia Touch) — conversational phrase; 55 false mentions confirmed
#   "you are"             → You Are (Geparlys) — SOTD daily thread-title artifact; 101 false mentions
#   "en route"            → En Route (Botanicae Expressions) — Davidoff Cool Water posts; 2 false mentions
#   "fragrance of summer" → Fragrance of Summer (M. Asam) — editorial headline phrase
#   "one only"            → One & Only (Swiss Arabian) — "the One & Only Parfumer" creator tagline;
#                            normalize_text("one & only") → "one only" (& stripped to space)
#   "one and only"        → One & Only (Swiss Arabian) — variant alias form
#   "good vibes"          → Good Vibes (Ricarda M.) — Jeremy Fragrance channel catchphrase
#                            ("Australia Fragrance Talk Good Vibes: #jeremyfragrance" ×4 videos)
#
# RES-AMB3 expansion (2026-05-17 — production audit of dashboard false positives):
#   "very well"   → Very Well (Berdoues) — generic approval phrase; 23 false mentions confirmed
#   "so happy"    → So Happy (Flormar) — conversational emotion; 12 false mentions confirmed
#   "too feminine"→ Too Feminine (Aigner) — common opinion phrase; 8 false mentions confirmed
#   "true icon"   → True Icon (Aigner) — superlative description; 1 false mention confirmed
#   "first class" → First Class (Aigner) — quality descriptor; 1 false mention confirmed
#
# RES-AMB4 expansion (2026-05-17 — audit-driven batch from RES-AMB-GLOBAL confirmed FPs):
#   "i will"          → I Will (Femascu) — future-tense sentence construction; 140 false mentions
#                        over 33 dates; breakout+acceleration_spike signals fired on Dashboard.
#                        RS evidence: "In this video, I will be reviewing..."; 0% brand hit.
#                        Guard choice: proximity (femascu is distinctive and usable as anchor).
#
#   "very pretty"     → Very Pretty (Michael Kors) — descriptor phrase in review prose; 3 false
#                        mentions. RS: Nui Cobalt / Maison Des Animaux posts; 0% brand hit.
#                        Guard choice: proximity (michael + kors are good anchors).
#
#   "so sexy"         → So Sexy! (Fiorucci) — exclamation/descriptor; 4 false mentions.
#                        normalize_text("So Sexy!") = "so sexy" (! stripped).
#                        RS: "omg this is not a fancy review... smells so sexy"; 0% brand hit.
#                        Guard choice: proximity (fiorucci is distinctive).
#
#   "day one"         → Day One (Smell Bent) — temporal phrase ("day one reviewing my collection");
#                        6 false mentions; wedding planning Reddit + review-journal temporal use.
#                        Guard choice: proximity (smell + bent together are distinctive).
#
#   "best man"        → Best Man (Helena Rubinstein) — Jeremy Fragrance "Best MAN Fragrance"
#                        video title descriptor (4×); wedding context; 8 false mentions.
#                        Guard choice: proximity (helena + rubinstein are distinctive).
#
#   "you you"         → You & You (Puig) — normalize_text("You & You") = "you you";
#                        conversational pronoun sequence; 7 false mentions.
#   "you and you"     → same entity, alias variant form.
#                        Guard choice: proximity (puig is distinctive).
#
#   "jasmine rose"    → Jasmine & Rose (Primark) — normalize_text("Jasmine & Rose") = "jasmine rose";
#                        ingredient/note pair in preference/recommendation posts; 4 false mentions.
#   "jasmine and rose"→ same entity, alias variant form.
#                        Guard choice: proximity (primark is distinctive; note pair alone is ambiguous).
#
#   "cedar wood"      → Cedar Wood (Monotheme) — note name used in Heretic Rhubarb Thief review;
#                        1 false mention; 1 signal + 1 snapshot fired on a FP event.
#                        Guard choice: proximity (monotheme is distinctive; "cedar wood" as a
#                        standalone 2-token phrase is always a note reference without brand context).
#
# "so so" (So...? So...?) is in _BLOCKED_MULTI_TOKEN_PHRASES — brand token "so" is too generic.
#
# "knize two" is fixed via _BLOCKED_SINGLE_WORD_ALIASES ("two") above — its
# only registered alias is the single token "two", not the phrase "knize two".
#
_AMBIGUOUS_PHRASE_GUARD: Dict[str, List[frozenset]] = {
    # RES-AMB1
    "i am":               [frozenset({"juicy", "couture"})],
    "right now":          [frozenset({"west", "third"})],
    "scent of":           [frozenset({"liu", "jo"})],
    "blue oud":           [frozenset({"ajwaa"})],
    "peace love":         [frozenset({"juicy", "couture"})],
    # RES-AMB2
    "so you":             [frozenset({"alia", "touch"})],
    "you are":            [frozenset({"geparlys"})],
    "en route":           [frozenset({"botanicae"})],
    "fragrance of summer":[frozenset({"asam"})],
    "one only":           [frozenset({"swiss", "arabian"})],
    "one and only":       [frozenset({"swiss", "arabian"})],
    "good vibes":         [frozenset({"ricarda"})],
    # RES-AMB3
    "very well":          [frozenset({"berdoues"})],
    "so happy":           [frozenset({"flormar"})],
    "too feminine":       [frozenset({"aigner"})],
    "true icon":          [frozenset({"aigner"})],
    "first class":        [frozenset({"aigner"})],
    # RES-AMB4 — audit-driven batch (2026-05-17)
    "i will":             [frozenset({"femascu"})],
    "very pretty":        [frozenset({"michael", "kors"})],
    "so sexy":            [frozenset({"fiorucci"})],
    "day one":            [frozenset({"smell", "bent"})],
    "best man":           [frozenset({"helena", "rubinstein"})],
    "you you":            [frozenset({"puig"})],              # normalize_text("You & You")
    "you and you":        [frozenset({"puig"})],              # alias variant
    "jasmine rose":       [frozenset({"primark"})],           # normalize_text("Jasmine & Rose")
    "jasmine and rose":   [frozenset({"primark"})],           # alias variant
    "cedar wood":         [frozenset({"monotheme"})],
}


def _check_brand_proximity(
    tokens: List[str],
    match_start: int,
    match_end: int,
    brand_token_sets: List[frozenset],
    window: int = 10,
) -> bool:
    """Return True if a brand token from any brand_token_set is within
    `window` tokens of the matched phrase [match_start:match_end].

    Looks at tokens before the phrase start and after the phrase end,
    but does not include the phrase tokens themselves in the context set
    (to avoid false positives from brand tokens that are part of the phrase).
    """
    lo = max(0, match_start - window)
    hi = min(len(tokens), match_end + window)
    context: Set[str] = set(tokens[lo:match_start]) | set(tokens[match_end:hi])
    for brand_tokens in brand_token_sets:
        if context & brand_tokens:
            return True
    return False


def make_resolver(db_path: str | None = None) -> "PerfumeResolver":
    """
    Factory: return a PerfumeResolver backed by Postgres or SQLite.

    Selection rule:
      - DATABASE_URL is set → PgResolverStore (Postgres resolver_* tables)
      - Otherwise          → FragranceMasterStore(db_path) (SQLite)

    In production (PTI_ENV=production): calls store.check_has_data() to fail
    fast if migration has not run yet, instead of silently resolving nothing.

    This is the preferred construction path for all production and script code.
    Direct PerfumeResolver(store=...) is still available for tests.
    """
    if os.environ.get("DATABASE_URL"):
        from perfume_trend_sdk.storage.entities.pg_resolver_store import PgResolverStore
        store = PgResolverStore()
        _log.info("[resolver] using Postgres resolver store (resolver_* tables)")
        # Fail fast in production if migration hasn't populated the tables yet.
        if os.environ.get("PTI_ENV", "dev").lower() == "production":
            store.check_has_data()
    else:
        if not db_path:
            db_path = "data/resolver/pti.db"
        store = FragranceMasterStore(db_path)
        _log.info("[resolver] using SQLite resolver store: %s", db_path)
    return PerfumeResolver(store=store)


class PerfumeResolver:
    version = "1.1"

    def __init__(
        self,
        db_path: str | None = None,
        *,
        store: Any = None,
    ) -> None:
        """
        Construct a PerfumeResolver.

        Preferred usage: call make_resolver() which picks the correct store
        automatically based on DATABASE_URL.

        Direct usage (backward-compatible):
          PerfumeResolver("data/resolver/pti.db")      # SQLite
          PerfumeResolver(store=PgResolverStore())     # Postgres
        """
        if store is not None:
            self.store = store
        elif db_path is not None:
            self.store = FragranceMasterStore(db_path)
        else:
            raise ValueError("Provide either db_path or store= to PerfumeResolver")

    def resolve_text(self, text: str) -> List[Dict[str, Any]]:
        """Slide a token window (1–_MAX_WINDOW) over normalised text and return all alias hits."""
        normalized = normalize_text(text)
        tokens = normalized.split()
        matches: List[Dict[str, Any]] = []
        seen: Set[Tuple[int, str]] = set()

        for size in range(_MAX_WINDOW, 0, -1):
            for i in range(len(tokens) - size + 1):
                phrase = " ".join(tokens[i : i + size])

                # --- Single-word alias safety guards (size == 1 only) ---
                if size == 1:
                    # Contraction-tail guard: "don't" normalises to ["don", "t"].
                    # If the next token is a known contraction tail, the current
                    # token was part of a contraction and must not match as an alias.
                    if (
                        i + 1 < len(tokens)
                        and tokens[i + 1] in _CONTRACTION_TAILS
                    ):
                        continue
                    # Generic single-word blocklist: words that are too short or
                    # too common to be matched safely in free-form social text.
                    if phrase in _BLOCKED_SINGLE_WORD_ALIASES:
                        continue

                # --- Multi-token unconditional block (RES-AMB3) ---
                # Common evaluative/conversational phrases where the brand
                # name is too generic to use as a proximity anchor.
                if phrase in _BLOCKED_MULTI_TOKEN_PHRASES:
                    continue

                result = self.store.get_perfume_by_alias(phrase)
                if result:
                    # Ambiguous phrase guard: common English phrases require
                    # brand proximity before being accepted as a match.
                    if phrase in _AMBIGUOUS_PHRASE_GUARD:
                        brand_token_sets = _AMBIGUOUS_PHRASE_GUARD[phrase]
                        if not _check_brand_proximity(
                            tokens, i, i + size, brand_token_sets
                        ):
                            _log.debug(
                                "[resolver] ambiguous phrase blocked (no brand proximity): %r → %r",
                                phrase,
                                result["canonical_name"],
                            )
                            continue
                    key = (result["perfume_id"], result["canonical_name"])
                    if key not in seen:
                        seen.add(key)
                        matches.append(result)
                        # Log alias matches — especially short-form single-token hits
                        canonical = result["canonical_name"]
                        if phrase != normalize_text(canonical):
                            _log.debug(
                                "[resolver] alias match: %r → %r (match_type=%s, confidence=%.2f)",
                                phrase,
                                canonical,
                                result.get("match_type", "?"),
                                result.get("confidence", 0.0),
                            )
                        if size == 1:
                            _log.info(
                                "[resolver] short-form alias: %r → %r",
                                phrase,
                                canonical,
                            )
        return matches

    def _extract_candidates(
        self, text: str, resolved_phrases: Set[str]
    ) -> List[str]:
        """
        Extract unresolved n-gram candidates from text.

        Strategy:
        1. Build a set of token-index spans covered by resolved matches so
           candidates that overlap a resolved span are not re-emitted.
        2. Slide a 2–4-token window; skip phrases that start with a stop word,
           consist only of generic terms, or are already resolved.
        """
        normalized = normalize_text(text)
        tokens = normalized.split()

        _STOP_WORDS: frozenset[str] = frozenset({
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
            "for", "of", "with", "my", "your", "their", "this", "that",
            "what", "how", "why", "when", "where", "which", "i", "we",
            "just", "have", "has", "is", "was", "are", "were", "be", "been",
            "do", "did", "does", "not", "it", "its", "so", "if", "as",
            "first", "new", "best", "most", "more", "very", "really",
        })

        # Build resolved token spans: for each resolved phrase, mark its
        # position(s) in the token list so we can skip overlapping candidates.
        resolved_spans: Set[int] = set()
        for phrase in resolved_phrases:
            phrase_tokens = phrase.split()
            plen = len(phrase_tokens)
            for i in range(len(tokens) - plen + 1):
                if tokens[i : i + plen] == phrase_tokens:
                    resolved_spans.update(range(i, i + plen))

        candidates: List[str] = []
        seen_candidates: Set[str] = set()

        # Only emit 2–4-token candidates (avoids noise from larger windows).
        for size in range(4, _MIN_CANDIDATE_TOKENS - 1, -1):
            for i in range(len(tokens) - size + 1):
                # Skip windows that overlap any resolved token position.
                window_indices = range(i, i + size)
                if any(idx in resolved_spans for idx in window_indices):
                    continue
                phrase = " ".join(tokens[i : i + size])
                if phrase in _GENERIC_TOKENS:
                    continue
                first_token = tokens[i]
                if first_token in _STOP_WORDS or first_token.isdigit():
                    continue
                if phrase not in seen_candidates:
                    seen_candidates.add(phrase)
                    candidates.append(phrase)

        return candidates

    def resolve_content_item(
        self,
        content_item: Dict[str, Any],
        *,
        emit_candidates: bool = True,
    ) -> Dict[str, Any]:
        """
        Resolve perfume mentions in a canonical content item.

        When MULTI_FIELD_RESOLVER_ENABLED=true: delegates to the multi-field
        resolver (SC1.3) which applies platform-specific field weights.

        When MULTI_FIELD_RESOLVER_ENABLED=false (default): uses the original
        single-field path (text_content only) — backward-compatible, no change.

        Args:
            content_item:    Dict with at least 'id' and 'text_content'.
            emit_candidates: When True, populate 'unresolved_mentions' with
                             candidate phrases not matched by the resolver.
                             Defaults to True.

        Returns:
            Dict with keys: content_item_id, resolver_version,
            resolved_entities, unresolved_mentions, alias_candidates.
            In multi-field mode, resolved_entities additionally include
            matched_field, field_confidence, final_confidence, all_fields.
        """
        from perfume_trend_sdk.resolvers.perfume_identity.multi_field_resolver import (
            is_enabled as _mf_enabled,
        )
        if _mf_enabled():
            return self._resolve_content_item_multi(
                content_item, emit_candidates=emit_candidates
            )
        return self._resolve_content_item_single(
            content_item, emit_candidates=emit_candidates
        )

    def _resolve_content_item_single(
        self,
        content_item: Dict[str, Any],
        *,
        emit_candidates: bool = True,
    ) -> Dict[str, Any]:
        """
        Original single-field resolution path (title/text_content only).
        Unchanged from v1.1 — used when multi-field flag is off.
        """
        text = content_item.get("text_content") or ""
        matches = self.resolve_text(text)

        resolved_phrases: Set[str] = set()
        resolved_entities = []
        for match in matches:
            resolved_entities.append({
                "entity_type": "perfume",
                "entity_id": str(match["perfume_id"]),
                "canonical_name": match["canonical_name"],
                "matched_from": text,
                "confidence": match["confidence"],
                "match_type": match["match_type"],
            })
            # Track the normalised alias phrase so candidates don't re-emit it.
            resolved_phrases.add(normalize_text(match["canonical_name"]))

        unresolved_mentions: List[str] = []
        if emit_candidates and text:
            candidates = self._extract_candidates(text, resolved_phrases)
            unresolved_mentions = candidates

        return {
            "content_item_id": content_item["id"],
            "resolver_version": self.version,
            "resolved_entities": resolved_entities,
            "unresolved_mentions": unresolved_mentions,
            "alias_candidates": [],
        }

    def _resolve_content_item_multi(
        self,
        content_item: Dict[str, Any],
        *,
        emit_candidates: bool = True,
    ) -> Dict[str, Any]:
        """
        SC1.3 multi-field resolution path (MULTI_FIELD_RESOLVER_ENABLED=true).

        Builds a text_signal from the content item, resolves each field with
        platform-specific weights, and aggregates into resolved_entities.

        Returns the same structure as the single-field path, extended with
        multi-field debug metadata on each resolved entity entry.
        """
        from perfume_trend_sdk.resolvers.perfume_identity.multi_field_resolver import (
            extract_signal_from_content_item,
            resolve_multi_field,
        )

        signal = extract_signal_from_content_item(content_item)
        mf_matches = resolve_multi_field(self, signal)

        resolved_phrases: Set[str] = set()
        resolved_entities = []
        for mf in mf_matches:
            resolved_entities.append({
                "entity_type": "perfume",
                "entity_id": mf.entity_id,
                "canonical_name": mf.canonical_name,
                "matched_from": mf.matched_field,
                "confidence": mf.final_confidence,
                "match_type": "multi_field",
                # SC1.3 extended debug fields
                "matched_field": mf.matched_field,
                "field_confidence": mf.field_confidence,
                "final_confidence": mf.final_confidence,
                "all_fields": mf.all_fields,
                "platform_key": mf.platform_key,
            })
            resolved_phrases.add(normalize_text(mf.canonical_name))

        # Unresolved candidates: use primary text for extraction
        primary_text = content_item.get("text_content") or ""
        unresolved_mentions: List[str] = []
        if emit_candidates and primary_text:
            unresolved_mentions = self._extract_candidates(primary_text, resolved_phrases)

        return {
            "content_item_id": content_item["id"],
            "resolver_version": self.version + "-mf",
            "resolved_entities": resolved_entities,
            "unresolved_mentions": unresolved_mentions,
            "alias_candidates": [],
        }
