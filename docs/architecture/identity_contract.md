# Identity Contract — Resolver Layer vs Market Engine

## Overview

The PTI SDK maintains two separate entity identity systems. This document defines
the contract between them, how IDs are translated, and what future pipeline code
must do when writing into market engine tables.

---

## Two Identity Systems

### System A — Resolver / Catalog Layer

**Owner:** entity resolution pipeline (ingestion, matching, growth engine)

| Table | PK type | Key field | Location |
|---|---|---|---|
| `brands` | Integer (autoincrement) | `normalized_name` | `pti.db` / resolver schema |
| `perfumes` | Integer (autoincrement) | `normalized_name` | `pti.db` / resolver schema |
| `aliases` | Integer | `normalized_alias_text` | `pti.db` / resolver schema |
| `fragrance_master` | Text (`fr_XXXXXX`) | `normalized_name` | `pti.db` / resolver schema |

**Purpose:** canonical entity identity for resolution. The resolver assigns Integer
IDs when it first sees a brand or perfume. These IDs are the stable identity anchors
for the alias store and entity matching pipeline.

**Contract:** resolver IDs are immutable once assigned. They must never be reused.

---

### System B — Market Engine

**Owner:** analytics, aggregation, and API serving layer

| Table | PK type | Key field | Location |
|---|---|---|---|
| `brands` | UUID (v4) | `slug` | `market_dev.db` / market schema |
| `perfumes` | UUID (v4) | `slug` | `market_dev.db` / market schema |
| `entity_market` | UUID (v4) | `entity_id` (string slug) | `market_dev.db` / market schema |
| `entity_timeseries_daily` | UUID (v4) | `entity_id` FK → `entity_market.id` | market schema |
| `entity_mentions` | UUID (v4) | `entity_id` FK → `entity_market.id` | market schema |
| `signals` | UUID (v4) | `entity_id` FK → `entity_market.id` | market schema |

**Purpose:** analytics-serving identity. Market UUIDs are used for all time-series,
mention, and signal writes. The API exposes `entity_market.entity_id` (string slug)
in URLs and responses — never raw UUIDs.

**Contract:** market UUIDs are stable once assigned. Never reassign a UUID to a
different entity.

---

## Bridge Layer

### Mapping Tables

Two tables in the **market engine database** store the cross-system mapping:

```sql
brand_identity_map (
    id                INTEGER PRIMARY KEY,
    resolver_brand_id INTEGER  NOT NULL UNIQUE,   -- System A
    market_brand_uuid TEXT(36) NOT NULL UNIQUE,   -- System B
    canonical_name    TEXT     NOT NULL,
    slug              TEXT     NOT NULL,
    created_at        DATETIME NOT NULL,
    updated_at        DATETIME NOT NULL
)

perfume_identity_map (
    id                  INTEGER PRIMARY KEY,
    resolver_perfume_id INTEGER  NOT NULL UNIQUE, -- System A
    market_perfume_uuid TEXT(36) NOT NULL UNIQUE, -- System B
    canonical_name      TEXT     NOT NULL,
    slug                TEXT     NOT NULL,
    created_at          DATETIME NOT NULL,
    updated_at          DATETIME NOT NULL
)
```

### Matching Key

The slug is the stable matching key between both systems.

**Brand slug:** `slugify(canonical_name)`
- Legacy: `slugify("Parfums de Marly")` → `"parfums-de-marly"`
- Market: stored directly as `brands.slug = "parfums-de-marly"` ✓

**Perfume slug:** `slugify(strip_concentration(canonical_name))`
- Legacy canonical_name includes brand + perfume + optional concentration suffix
  e.g. `"Indult Tihota Eau de Parfum"`
- After stripping: `"Indult Tihota"` → `slugify()` → `"indult-tihota"`
- Market slug: `"indult-tihota"` ✓

### Sync Job

Run after any change to either catalog:

```bash
python scripts/sync_identity_map.py \
    --resolver-db outputs/pti.db \
    --market-db outputs/market_dev.db \
    --verbose
```

---

## ID Translation Rules

### Rule 1 — Ingestion writes always use market UUIDs

All writes into `entity_mentions`, `entity_timeseries_daily`, and `signals`
must use the `entity_market.id` UUID. Never store a resolver Integer ID in
these tables.

```python
# Correct
entity_uuid = resolver.perfume_uuid(legacy_perfume_id=7)
session.add(EntityMention(entity_id=entity_uuid, ...))

# Wrong — resolver ID stored in market table
session.add(EntityMention(entity_id=7, ...))
```

### Rule 2 — Resolver output feeds market engine through canonical_name

The aggregation job receives resolved signals containing `canonical_name` strings.
It upserts `entity_market` records keyed by `entity_id = canonical_name`, then uses
the resulting UUID for downstream writes.

```
resolved_signals.canonical_name
    → entity_market.entity_id (upsert, get UUID)
    → entity_timeseries_daily.entity_id (UUID)
    → entity_mentions.entity_id (UUID)
    → signals.entity_id (UUID)
```

### Rule 3 — API never exposes UUIDs directly

The API uses `entity_market.entity_id` (the human-readable canonical name string)
in all URL paths and response bodies. UUIDs are internal only.

```
GET /api/v1/entities/Parfums de Marly Delina   ← canonical name in URL
response.entity.id = "0fa3bbc6-..."            ← UUID in response body (for reference)
response.entity.entity_id = "Parfums de Marly Delina"  ← slug for links
```

### Rule 4 — New entities created by aggregation, not by resolver

When the aggregation job encounters a canonical name not yet in `entity_market`,
it creates a new `entity_market` row and assigns a UUID. The resolver does **not**
write to market engine tables. The sync job later creates the mapping row.

---

## Future Production Layout (PostgreSQL)

In the current dev setup, both databases are SQLite files. The architectural
split maps cleanly to PostgreSQL schemas:

```
PostgreSQL cluster
├── schema: resolver
│   ├── brands          (Integer PK — resolver identity)
│   ├── perfumes        (Integer PK — resolver identity)
│   ├── aliases
│   └── fragrance_master
│
├── schema: market
│   ├── entity_market               (UUID PK)
│   ├── brands                      (UUID PK — market identity)
│   ├── perfumes                    (UUID PK — market identity)
│   ├── entity_timeseries_daily     (UUID entity_id FK)
│   ├── entity_mentions             (UUID entity_id FK)
│   └── signals                     (UUID entity_id FK)
│
└── schema: bridge
    ├── brand_identity_map          (Integer ↔ UUID)
    └── perfume_identity_map        (Integer ↔ UUID)
```

**Recommendation:** use PostgreSQL schemas (not separate databases) in production.
Cross-schema joins are native and efficient. The bridge schema can then be queried
without separate connections.

**Migration path from dev to production:**
1. Run Alembic `upgrade head` on a fresh PostgreSQL database (creates market schema)
2. Load resolver catalog into `resolver` schema via `load_fragrance_master` workflow
3. Seed market catalog via `scripts/seed_market_catalog.py`
4. Run `scripts/sync_identity_map.py` to populate bridge schema
5. Run backfill aggregation jobs for historical dates

---

## What Future Jobs Must Do

Any job that ingests data and writes to market engine tables must follow this pattern:

```python
from perfume_trend_sdk.bridge.identity_resolver import IdentityResolver

resolver = IdentityResolver("outputs/market_dev.db")

# When you have a resolver perfume id (from resolved_signals join)
market_uuid = resolver.perfume_uuid(legacy_perfume_id=row["perfume_id"])
if market_uuid is None:
    # Entity not yet in market engine — run sync job first, or
    # let the aggregation job create the entity_market row on next run
    continue

# Write to market table using UUID
session.add(EntityMention(entity_id=market_uuid, ...))
```

---

## Invariants (never violate)

1. `entity_market.entity_id` (string) is the **public API key** — never change it
   for an existing entity.
2. `entity_market.id` (UUID) is the **internal analytics key** — all FK references
   in market tables use this.
3. `brands.id` (Integer, resolver) and `brands.id` (UUID, market) are **different
   IDs for different purposes** — the mapping tables are the only safe translation path.
4. The resolver catalog is **read-mostly** from the market engine's perspective. The
   market engine does not write back to resolver tables.
