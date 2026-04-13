-- BRANDS
CREATE TABLE IF NOT EXISTS brands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL
);

-- PERFUMES
CREATE TABLE IF NOT EXISTS perfumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand_id INTEGER,
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    FOREIGN KEY (brand_id) REFERENCES brands(id)
);

-- ALIASES
CREATE TABLE IF NOT EXISTS aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alias_text TEXT NOT NULL,
    normalized_alias_text TEXT NOT NULL,
    entity_type TEXT NOT NULL, -- brand / perfume
    entity_id INTEGER NOT NULL,
    match_type TEXT, -- manual / exact / fuzzy / ai
    confidence REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- MENTIONS
CREATE TABLE IF NOT EXISTS mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_text TEXT,
    normalized_text TEXT,
    source TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- RESOLUTION RESULTS
CREATE TABLE IF NOT EXISTS resolutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mention_id INTEGER,
    entity_type TEXT,
    entity_id INTEGER,
    resolution_method TEXT,
    confidence REAL,
    FOREIGN KEY (mention_id) REFERENCES mentions(id)
);

-- UNRESOLVED
CREATE TABLE IF NOT EXISTS unresolved (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mention_id INTEGER,
    candidate_text TEXT,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
