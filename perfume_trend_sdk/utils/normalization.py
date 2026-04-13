import re

STOPWORDS = {
    "top", "best", "what", "are", "is", "for", "the", "and",
    "with", "this", "that", "from", "into", "your",
    "get", "grab", "last", "longer", "through", "here",
    "these", "those", "have", "has", "popular", "new", "about",
    "chat", "thoughts", "would", "could", "should", "also",
    "very", "more", "most", "some", "many", "much",
    "attractive", "unique", "shorts", "far",
}

GENERIC_PERFUME_WORDS = {
    "fragrance", "fragrances",
    "perfume", "perfumes",
    "cologne", "colognes",
    "scent", "scents",
}

PERFUME_HINTS = {
    "parfum", "perfume", "fragrance",
    "oud", "vanilla", "rose", "musk",
    "amber", "elixir", "intense",
    "noir", "love", "flora",
}

PHRASE_BLACKLIST = [
    r"\btop\s+\d+\b",
    r"\bout\s+of\s+\d+\b",
    r"\bworst\s+to\s+best\b",
    r"\bbest\s+to\s+worst\b",
    r"\bthrough\s+the\s+links\b",
    r"\bgrab\s+them\s+here\b",
    r"\bit\s+would\s+be\b",
    r"\blast\s+longer\s+than\b",
    r"\bnew\s+fragrance\s+releases\b",
    r"\bcomplimented\s+fragrances\b",
    r"\bwe\s+chat\b",
    r"\bfar\s+from\b",
]

CONCENTRATION_PATTERNS = {
    "body_spray": [
        r"\bbody spray\b",
        r"\bbody mist\b",
    ],
    "edp": [
        r"\bedp\b",
        r"\beau de parfum\b",
    ],
    "edt": [
        r"\bedt\b",
        r"\beau de toilette\b",
    ],
    "extrait": [
        r"\bextrait\b",
        r"\bextrait de parfum\b",
    ],
    "parfum": [
        r"\bparfum\b",
    ],
}


def normalize_text(text: str):
    if not text:
        return "", None

    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    concentration = None
    for label, patterns in CONCENTRATION_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text):
                concentration = label
                text = re.sub(pattern, "", text).strip()
                text = re.sub(r"\s+", " ", text)
                break
        if concentration:
            break

    return text, concentration


def clean_candidate_entity(candidate: str):
    words = candidate.split()

    # отрезать generic слова в начале
    while words and words[0] in GENERIC_PERFUME_WORDS:
        words = words[1:]

    # отрезать generic слова в конце
    while words and words[-1] in GENERIC_PERFUME_WORDS:
        words = words[:-1]

    cleaned = " ".join(words).strip()

    if not cleaned:
        return None

    return cleaned


def is_blacklisted(candidate: str) -> bool:
    for pattern in PHRASE_BLACKLIST:
        if re.search(pattern, candidate):
            return True
    return False


def is_valid_candidate(candidate: str) -> bool:
    words = candidate.split()

    if len(candidate) < 2:
        return False

    # если все слова стоп-слова — мусор
    if all(w in STOPWORDS for w in words):
        return False

    # если только цифры
    if candidate.isdigit():
        return False

    return True


def extract_candidate_phrases(text: str, max_n: int = 4):
    normalized, concentration = normalize_text(text)
    tokens = normalized.split()

    candidates = set()
    if normalized:
        candidates.add(normalized)

    for n in range(1, max_n + 1):
        for i in range(len(tokens) - n + 1):
            phrase = " ".join(tokens[i:i + n]).strip()
            if phrase:
                candidates.add(phrase)

    filtered = []
    for c in sorted(candidates, key=lambda x: (len(x.split()), len(x)), reverse=True):
        if is_blacklisted(c):
            continue
        c = clean_candidate_entity(c)
        if c and is_valid_candidate(c):
            filtered.append(c)

    return filtered, concentration
