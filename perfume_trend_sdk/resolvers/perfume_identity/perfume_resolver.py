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


def make_resolver(db_path: str | None = None) -> "PerfumeResolver":
    """
    Factory: return a PerfumeResolver backed by Postgres or SQLite.

    Selection rule:
      - DATABASE_URL is set → PgResolverStore (Postgres resolver_* tables)
      - Otherwise          → FragranceMasterStore(db_path) (SQLite)

    This is the preferred construction path for all production and script code.
    Direct PerfumeResolver(store=...) is still available for tests.
    """
    if os.environ.get("DATABASE_URL"):
        from perfume_trend_sdk.storage.entities.pg_resolver_store import PgResolverStore
        store = PgResolverStore()
        _log.info("[resolver] using Postgres resolver store (resolver_* tables)")
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
                result = self.store.get_perfume_by_alias(phrase)
                if result:
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

        Args:
            content_item:    Dict with at least 'id' and 'text_content'.
            emit_candidates: When True, populate 'unresolved_mentions' with
                             candidate phrases not matched by the resolver.
                             Defaults to True.

        Returns:
            Dict with keys: content_item_id, resolver_version,
            resolved_entities, unresolved_mentions, alias_candidates.
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
