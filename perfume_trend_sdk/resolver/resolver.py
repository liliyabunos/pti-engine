import sqlite3

from rapidfuzz import fuzz

from perfume_trend_sdk.utils.normalization import extract_candidate_phrases

DB_PATH = "perfume_trend_sdk/db/perfume.db"


def get_aliases(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT id, normalized_alias_text, entity_type, entity_id FROM aliases")
    return cursor.fetchall()


def resolve_text(text: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    candidates, concentration = extract_candidate_phrases(text)

    # 1. EXACT MATCH on any candidate
    for candidate in candidates:
        cursor.execute(
            "SELECT entity_type, entity_id FROM aliases WHERE normalized_alias_text = ?",
            (candidate,),
        )
        result = cursor.fetchone()
        if result:
            conn.close()
            return {
                "method": "exact",
                "candidate": candidate,
                "entity_type": result[0],
                "entity_id": result[1],
                "confidence": 1.0,
                "concentration": concentration,
            }

    # 2. FUZZY MATCH on any candidate
    aliases = get_aliases(conn)

    best_score = 0
    best_match = None
    best_candidate = None

    for candidate in candidates:
        for _, alias_text, entity_type, entity_id in aliases:
            score = fuzz.ratio(candidate, alias_text)
            if score > best_score:
                best_score = score
                best_match = (entity_type, entity_id)
                best_candidate = candidate

    conn.close()

    if best_score >= 92:
        return {
            "method": "fuzzy_high",
            "candidate": best_candidate,
            "entity_type": best_match[0],
            "entity_id": best_match[1],
            "confidence": best_score / 100,
            "concentration": concentration,
        }

    if best_score >= 80:
        return {
            "method": "fuzzy_mid",
            "candidate": best_candidate,
            "entity_type": best_match[0],
            "entity_id": best_match[1],
            "confidence": best_score / 100,
            "concentration": concentration,
        }

    return {
        "method": "unresolved",
        "candidate": best_candidate or text,
        "confidence": best_score / 100,
        "concentration": concentration,
    }
