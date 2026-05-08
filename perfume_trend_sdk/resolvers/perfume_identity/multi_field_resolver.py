from __future__ import annotations

"""
SC1.3 — Multi-field resolver adapter.

Extends PerfumeResolver to accept a structured text_signal dict with
platform-specific field weights, rather than a single text_content string.

Feature flag: MULTI_FIELD_RESOLVER_ENABLED=false (default).
Deploy disabled. Enable only after replay report confirms no regression.

Platform key routing:
  youtube         → title(1.0) description(0.5) hashtags(0.3)
  reddit          → body(1.0) title(0.7) hashtags(0.3)
  tiktok_derived  → referencing_context(1.0) hashtags(0.5) description(0.3) title(0.2)
  tiktok_direct   → user_context(1.0) hashtags(0.6) referencing_context(0.4)
                     description(0.4) title(0.5)
  tiktok_layer3   → user_context(0.8) title(0.7) hashtags(0.6) description(0.5)

Confidence aggregation:
  final_confidence = max(field_weight * raw_confidence) over all matched fields.
  Matches below MULTI_FIELD_CONFIDENCE_THRESHOLD (0.3) are suppressed.

Generic title protection:
  TikTok-only: titles that are entirely generic social phrases ("omg", "you need this",
  "run don't walk", etc.) do not produce confident matches alone.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import PerfumeResolver

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    """Return True only when MULTI_FIELD_RESOLVER_ENABLED=true."""
    return os.environ.get("MULTI_FIELD_RESOLVER_ENABLED", "false").lower() == "true"


# ---------------------------------------------------------------------------
# Platform weights
# ---------------------------------------------------------------------------

# Maps platform_key -> {field_name -> weight}
# Weights express how much trust to give a match from each field.
# A match from field F with raw confidence C produces weighted_confidence = weight * C.
PLATFORM_WEIGHTS: Dict[str, Dict[str, float]] = {
    "youtube": {
        "title": 1.0,          # YouTube title is the primary entity signal
        "description": 0.5,    # description is longer / noisier
        "hashtags": 0.3,
    },
    "reddit": {
        "body": 1.0,           # full post body (title + selftext)
        "title": 0.7,          # title alone is also useful
        "hashtags": 0.3,       # Reddit rarely uses hashtags, but handle gracefully
    },
    "tiktok_derived": {
        # Derived = TikTok URL found inside another platform's content.
        # Only referencing_context (the surrounding text) is reliable.
        # oEmbed/title field is often garbage ("TikTok" or unavailable).
        "referencing_context": 1.0,
        "hashtags": 0.5,
        "description": 0.3,    # caption when available
        "title": 0.2,          # oEmbed title — low trust
    },
    "tiktok_direct": {
        # Direct = TikTok URL submitted by operator (submit-source flow).
        # user_context (operator-supplied description) is most reliable.
        "user_context": 1.0,
        "hashtags": 0.6,
        "referencing_context": 0.4,
        "description": 0.4,    # caption when available
        "title": 0.5,          # caption-derived title — medium trust
    },
    "tiktok_layer3": {
        # Layer 3 = seeded watchlist creator monitoring.
        # Currently metadata-only (no video discovery in SC1.2C).
        # Weights prepared for when video title/description become available.
        "user_context": 0.8,
        "title": 0.7,
        "hashtags": 0.6,
        "description": 0.5,
    },
}

# Minimum weighted confidence below which a match is suppressed.
MULTI_FIELD_CONFIDENCE_THRESHOLD: float = 0.3

# ---------------------------------------------------------------------------
# YouTube title noise filter
# ---------------------------------------------------------------------------

# Fragrance aliases that are also common English phrases. When the ONLY evidence
# for a match comes from a YouTube title, these produce false positives.
# ("I will", "You Are", etc. are real fragrance names in the catalog but are
# too short/generic to trust in free-form YouTube video titles.)
#
# Rule: applied post-resolution, only when:
#   (a) platform_key == "youtube"
#   (b) the entity was matched ONLY in the "title" field (not corroborated by
#       description or hashtags)
#   (c) the normalized canonical_name is in this set.
#
# Multi-field matches (title + description) bypass this filter because the
# second field provides independent corroboration.
_YOUTUBE_TITLE_NOISE_ALIASES: frozenset[str] = frozenset({
    # Fragrance names that are common English phrases — ambiguous in YouTube titles
    "i will",
    "you are",
    "beach vibes",
    "so sweet",
    "forever",
    "love story",
    "good girl",
    "bad boy",
    "crazy",
    "cool",
    "cool water",        # too short to distinguish from generic "cool water" descriptions
    "desire",
    "legend",
    "hero",
    "brave",
    "sport",
    # Common fragrance descriptors that are also real perfume names
    "orange blossom",    # fragrance note & generic topic — fires on "orange blossom fragrances" lists
    "scent of",          # fragment alias — fires on "Scent of the Day" in video titles
    "men's cologne",     # fires when "for men" + "#cologne" are adjacent after hashtag expansion
})


# ---------------------------------------------------------------------------
# Generic title protection (TikTok only)
# ---------------------------------------------------------------------------

# Social phrases that alone should not produce a high-confidence match.
# These are checked against the normalized title text.
_GENERIC_TITLE_PHRASES: frozenset[str] = frozenset({
    "you need this",
    "run dont walk",
    "run don't walk",
    "omg",
    "must try",
    "best perfume",
    "best cologne",
    "this is insane",
    "game changer",
    "new favorite",
    "cant stop",
    "can't stop",
    "obsessed",
    "holy grail",
    "unboxing",
    "haul",
    "my collection",
    "top picks",
    "smell good",
    "smell amazing",
    "smells amazing",
    "smells so good",
    "wait for it",
    "trust me",
    "try this",
    "no way",
    "iconic",
})


def _is_generic_tiktok_title(text: str) -> bool:
    """
    Return True if this title consists mostly of generic social phrases.

    Used for TikTok-derived and TikTok-direct items to suppress low-signal
    title-only matches. Multi-token entity names (e.g. "baccarat rouge 540")
    are specific enough to pass even if the title also has generic phrases.
    """
    if not text:
        return True
    lowered = text.lower().strip()
    for phrase in _GENERIC_TITLE_PHRASES:
        if phrase in lowered:
            return True
    # Also block very short single-word generic titles
    words = lowered.split()
    if len(words) <= 3 and all(w in {
        "perfume", "cologne", "fragrance", "scent", "omg",
        "wow", "lol", "yes", "no", "it",
    } for w in words):
        return True
    return False


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FieldMatch:
    """A single entity match found in one resolver field."""
    entity_id: str
    canonical_name: str
    raw_confidence: float
    match_type: str
    field_name: str
    field_weight: float

    @property
    def weighted_confidence(self) -> float:
        return self.field_weight * self.raw_confidence


@dataclass
class MultiFieldMatch:
    """Aggregated entity match across all fields."""
    entity_id: str
    canonical_name: str
    # Aggregated
    final_confidence: float
    matched_field: str          # field that produced the highest weighted confidence
    field_confidence: float     # raw resolver confidence in matched_field
    all_fields: List[str]       # all fields that matched this entity (de-duped)
    # Debug / routing info
    platform: str
    platform_key: str
    source_method: Optional[str]
    tiktok_layer: Optional[int]
    # Reserved for future use
    matched_alias: Optional[str] = None


# ---------------------------------------------------------------------------
# Platform key routing
# ---------------------------------------------------------------------------

def _get_platform_key(signal: Dict[str, Any]) -> str:
    """
    Derive the platform_key used to select PLATFORM_WEIGHTS.

    Routing:
      tiktok + layer=3             → tiktok_layer3
      tiktok + source_method=derived or mention_weight_override=0.0 → tiktok_derived
      tiktok + anything else       → tiktok_direct
      reddit                       → reddit
      everything else (youtube)    → youtube
    """
    platform = (signal.get("platform") or "").lower()
    if platform == "tiktok":
        if signal.get("tiktok_layer") == 3:
            return "tiktok_layer3"
        mwo = signal.get("mention_weight_override")
        source_method = (signal.get("source_method") or "").lower()
        if source_method == "derived" or mwo == 0.0:
            return "tiktok_derived"
        return "tiktok_direct"
    if platform == "reddit":
        return "reddit"
    return "youtube"  # default for youtube and unknown platforms


# ---------------------------------------------------------------------------
# Signal extraction from content item
# ---------------------------------------------------------------------------

def extract_signal_from_content_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a text_signal dict from a normalized canonical content item.

    This is the bridge between the existing normalizer output and the
    multi-field resolver input schema.

    Field mapping per platform:
      YouTube:  title=item.title  description=item.text_content  hashtags=item.hashtags
      Reddit:   title=item.title  body=item.text_content         hashtags=item.hashtags
      TikTok derived:  referencing_context=item.referencing_context
                       description=item.text_content  hashtags=item.hashtags  title=None
      TikTok direct:   user_context=item.text_content  hashtags=item.hashtags  title=None
    """
    platform = (item.get("source_platform") or "youtube").lower()
    hashtags: List[str] = item.get("hashtags") or []
    hashtag_text: Optional[str] = " ".join(hashtags) if hashtags else None

    # Determine source method for TikTok
    source_method: Optional[str] = None
    if platform == "tiktok":
        mwo = item.get("mention_weight_override")
        if mwo == 0.0:
            source_method = "derived"
        else:
            source_method = "direct"

    # user_context = text_content for TikTok direct items
    user_context: Optional[str] = None
    if platform == "tiktok" and source_method == "direct":
        user_context = item.get("text_content")

    return {
        "title": item.get("title"),
        "description": item.get("text_content"),
        "hashtags": hashtag_text,
        "body": item.get("text_content"),   # Reddit: already title+selftext
        "referencing_context": item.get("referencing_context"),
        "user_context": user_context,
        "audio_transcript": None,            # reserved — SC1.4T
        "ocr_overlays": None,               # reserved — future
        "platform": platform,
        "source_method": source_method,
        "tiktok_layer": item.get("tiktok_layer"),
        "mention_weight_override": item.get("mention_weight_override"),
    }


# ---------------------------------------------------------------------------
# Core multi-field resolution
# ---------------------------------------------------------------------------

def resolve_multi_field(
    resolver: "PerfumeResolver",
    signal: Dict[str, Any],
    *,
    confidence_threshold: float = MULTI_FIELD_CONFIDENCE_THRESHOLD,
) -> List[MultiFieldMatch]:
    """
    Resolve entities from a structured text_signal using platform-weighted fields.

    Args:
        resolver:             PerfumeResolver instance (uses resolve_text internally).
        signal:               text_signal dict (see extract_signal_from_content_item).
        confidence_threshold: Matches below this weighted confidence are dropped.

    Returns:
        List of MultiFieldMatch, sorted by final_confidence descending.
        Empty when no field contains a resolvable entity above the threshold.
    """
    platform_key = _get_platform_key(signal)
    weights = PLATFORM_WEIGHTS.get(platform_key, PLATFORM_WEIGHTS["youtube"])

    # Map field_name -> text to resolve
    field_texts: Dict[str, Optional[str]] = {
        "title": signal.get("title"),
        "description": signal.get("description"),
        "hashtags": signal.get("hashtags"),
        "body": signal.get("body"),
        "referencing_context": signal.get("referencing_context"),
        "user_context": signal.get("user_context"),
        # audio_transcript + ocr_overlays reserved — not included even if present
    }

    # Collect per-field matches: entity_id -> list[FieldMatch]
    entity_fields: Dict[str, List[FieldMatch]] = {}

    for fname, weight in weights.items():
        if weight <= 0.0:
            continue
        text = field_texts.get(fname)
        if not text or not text.strip():
            continue

        # Generic title protection: suppress TikTok title resolution when the
        # title is purely a social engagement phrase with no entity signal.
        if fname == "title" and platform_key in ("tiktok_derived", "tiktok_direct"):
            if _is_generic_tiktok_title(text):
                _log.debug(
                    "[multi_field] generic_title_suppressed platform_key=%s title=%r",
                    platform_key, text[:80],
                )
                continue

        matches = resolver.resolve_text(text)
        for m in matches:
            eid = str(m["perfume_id"])
            fm = FieldMatch(
                entity_id=eid,
                canonical_name=m["canonical_name"],
                raw_confidence=m.get("confidence", 1.0),
                match_type=m.get("match_type", "exact"),
                field_name=fname,
                field_weight=weight,
            )
            if eid not in entity_fields:
                entity_fields[eid] = []
            entity_fields[eid].append(fm)

    results: List[MultiFieldMatch] = []

    for eid, fms in entity_fields.items():
        best = max(fms, key=lambda fm: fm.weighted_confidence)

        if best.weighted_confidence < confidence_threshold:
            _log.debug(
                "[multi_field] suppressed entity=%s weighted_conf=%.3f threshold=%.3f",
                best.canonical_name, best.weighted_confidence, confidence_threshold,
            )
            continue

        all_fields = sorted({fm.field_name for fm in fms})

        # YouTube title noise filter: suppress matches whose canonical_name is a
        # known ambiguous alias (common English phrase) UNLESS the match is also
        # corroborated by a second field (description, hashtags, body).
        if platform_key == "youtube":
            canonical_lower = best.canonical_name.lower().strip()
            if canonical_lower in _YOUTUBE_TITLE_NOISE_ALIASES:
                if all_fields == ["title"]:
                    # Title-only match with ambiguous alias → suppress
                    _log.debug(
                        "[multi_field] youtube_title_noise suppressed entity=%s "
                        "(title-only, ambiguous alias)",
                        best.canonical_name,
                    )
                    continue
                # Found in another field too → allow (corroborated)

        results.append(MultiFieldMatch(
            entity_id=eid,
            canonical_name=best.canonical_name,
            final_confidence=best.weighted_confidence,
            matched_field=best.field_name,
            field_confidence=best.raw_confidence,
            all_fields=all_fields,
            platform=signal.get("platform", ""),
            platform_key=platform_key,
            source_method=signal.get("source_method"),
            tiktok_layer=signal.get("tiktok_layer"),
        ))

    return sorted(results, key=lambda m: m.final_confidence, reverse=True)
