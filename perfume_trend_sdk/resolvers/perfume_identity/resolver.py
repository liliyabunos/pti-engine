from rapidfuzz import fuzz

from perfume_trend_sdk.storage.entities.fragrance_master_store import FragranceMasterStore
from perfume_trend_sdk.utils.alias_generator import normalize_text
from perfume_trend_sdk.utils.normalization import extract_candidate_phrases

DB_PATH = "perfume_trend_sdk/local_dev.sqlite"

_store = FragranceMasterStore(DB_PATH)


def _fuzzy_match(candidates: list, store: FragranceMasterStore) -> dict | None:
    with store.connect() as conn:
        aliases = conn.execute(
            "SELECT normalized_alias_text, entity_id FROM aliases WHERE entity_type = 'perfume'"
        ).fetchall()

    if not aliases:
        return None

    best_score = 0
    best_alias_entity_id = None
    best_candidate = None

    for candidate in candidates:
        for alias_text, entity_id in aliases:
            score = fuzz.ratio(candidate, alias_text)
            if score > best_score:
                best_score = score
                best_alias_entity_id = entity_id
                best_candidate = candidate

    if best_score >= 92:
        method = "fuzzy_high"
    elif best_score >= 80:
        method = "fuzzy_mid"
    else:
        return None

    with store.connect() as conn:
        row = conn.execute(
            "SELECT canonical_name FROM perfumes WHERE id = ?",
            (best_alias_entity_id,),
        ).fetchone()

    if row is None:
        return None

    return {
        "method": method,
        "candidate": best_candidate,
        "entity_type": "perfume",
        "entity_id": best_alias_entity_id,
        "canonical_name": row["canonical_name"],
        "confidence": round(best_score / 100, 3),
    }


def resolve_mention(raw_text: str) -> dict:
    candidates, concentration = extract_candidate_phrases(raw_text)

    # 1. Exact match against fragrance_master aliases
    for candidate in candidates:
        result = _store.get_perfume_by_alias(candidate)
        if result:
            return {
                "method": "exact",
                "candidate": candidate,
                "entity_type": "perfume",
                "entity_id": result["perfume_id"],
                "canonical_name": result["canonical_name"],
                "confidence": 1.0,
                "concentration": concentration,
            }

    # 2. Fuzzy match against fragrance_master aliases
    fuzzy = _fuzzy_match(candidates, _store)
    if fuzzy:
        fuzzy["concentration"] = concentration
        return fuzzy

    # 3. Unresolved → Discovery Layer
    return {
        "method": "unresolved",
        "candidate": candidates[0] if candidates else normalize_text(raw_text),
        "entity_type": None,
        "entity_id": None,
        "canonical_name": None,
        "confidence": 0.0,
        "concentration": concentration,
    }
