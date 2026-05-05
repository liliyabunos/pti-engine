# SDK Architecture & Sprint Plan

Extracted from CLAUDE.md on 2026-05-05.

## Project Identity

**Working title:** Perfume Trend Intelligence SDK (PTI SDK)
**Internal aliases:** PTI SDK, Perfume Signals Engine, Fragrance Trend OS

**Mission:** Build a modular platform for collecting, normalizing, analyzing, and packaging perfume trend signals from the US market (social platforms, retail sources, commercial data) — reusable across media, app, B2B analytics, affiliate models, and future data APIs.

---

## Technology Stack

| Concern | Choice |
|---------|--------|
| Language | Python 3.11+ |
| Data validation | Pydantic v2 |
| HTTP client | requests / httpx |
| Browser automation | Playwright (when needed) |
| Storage (dev) | SQLite with PostgreSQL-ready abstractions |
| File formats | JSONL, CSV, Markdown |
| Scheduling | cron / GitHub Actions / lightweight task runner |
| Testing | pytest |
| Logging | Structured JSON logs |

---

## AI Layer Rules (NEVER VIOLATE)

- AI extractors must be model-agnostic — logic lives in engine, not pipeline
- All AI engines must return the same unified output schema
- AI is an optional layer — pipeline must work without it
- Rule-based extractor remains the fallback
- Always route through `get_extractor(provider)` — never instantiate engines directly in pipeline
- Source intelligence is a first-class signal — not metadata decoration

---

## Architecture Principles (NEVER VIOLATE)

1. **Interfaces first, then implementation** — define contracts before writing logic
2. **No source dictates the data model** — connectors adapt to canonical schema, not the other way around
3. **No analytics inside connectors** — connectors return raw data only
4. **Each layer stores its own result separately** — raw ≠ normalized ≠ signals ≠ enriched
5. **Every block must have a clear replacement point** — weak coupling everywhere
6. **Historical data must be reprocessable** — never overwrite raw with interpreted data
7. **Loose coupling** — connector knows nothing about scoring; scoring doesn't depend on collection method

---

## Architecture Layers

| Layer | Name | Responsibility |
|-------|------|----------------|
| 1 | Core | Config loading, module registry, pipeline routing, error handling, logging, versioning |
| 2 | Connectors | Fetch raw data from external sources, maintain cursors, return raw payload |
| 3 | Normalization | Convert raw source into canonical CanonicalContentItem |
| 4 | Extraction | Extract perfume/brand/note/price/retailer mentions, classify signal type |
| 5 | Resolution | Deduplicate entities, build alias mapping, identity layer |
| 6 | Enrichment | Add official notes, prices, retailer list, discount signals |
| 7 | Scoring & Analytics | Compute trend score, creator influence, note momentum, rising perfumes |
| 8 | Output / Delivery | Publish to CSV, JSON, Google Sheets, markdown report, API |
| 9 | SDK Layer | Module interfaces, developer docs, config templates, test fixtures |

---

## Project Structure

```
perfume_trend_sdk/
  pyproject.toml
  README.md
  .env.example
  configs/
    app.yaml
    sources/
      youtube.yaml
      tiktok_watchlist.yaml
      instagram_watchlist.yaml
      retail_prices.yaml
    watchlists/
      creators_us.yaml
      brands_us.yaml
      retailers_us.yaml
    scoring/
      trend_score.yaml
  core/
    config/
    registry/
    pipeline/
    logging/
    errors/
    models/
    types/
    utils/
  connectors/
    youtube/
    tiktok_watchlist/
    instagram_watchlist/
    retail_prices/
    brand_sites/
  normalizers/
    social_content/
    commerce_snapshot/
  extractors/
    perfume_mentions/
    brand_mentions/
    note_mentions/
    price_mentions/
    retailer_mentions/
    recommendation_signals/
  resolvers/
    perfume_identity/
    brand_identity/
  enrichers/
    perfume_metadata/
    pricing/
    discounts/
  scorers/
    trend_score/
    creator_weight/
    note_momentum/
  storage/
    interfaces/
    raw/
    normalized/
    signals/
    entities/
    analytics/
  publishers/
    json/
    csv/
    markdown/
    sheets/
  workflows/
    ingest_social_content.py
    enrich_market_data.py
    build_weekly_report.py
  tests/
    unit/
    integration/
    fixtures/
  docs/
    schemas/
    module_contracts/
```

---

## Base Types (Core)

```python
class PipelineContext(BaseModel):
    run_id: str
    workflow_name: str
    started_at: datetime
    environment: str
    schema_version: str
    extractor_version: str | None = None
    scoring_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class FetchCursor(BaseModel):
    source_name: str
    cursor_type: str
    cursor_value: str | None = None
    updated_at: datetime

class FetchSessionResult(BaseModel):
    source_name: str
    fetched_count: int
    success_count: int
    failed_count: int
    next_cursor: FetchCursor | None = None
    raw_items: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
```

---

## SDK Module Contracts (Python Protocols)

```python
class SourceConnector(Protocol):
    name: str
    version: str
    def validate_config(self, config: dict[str, Any]) -> None: ...
    def healthcheck(self) -> bool: ...
    def get_cursor(self) -> FetchCursor | None: ...
    def set_cursor(self, cursor: FetchCursor) -> None: ...
    def fetch(self, context: PipelineContext, limit: int | None = None) -> FetchSessionResult: ...

class Normalizer(Protocol):
    name: str
    version: str
    def normalize(self, raw_item: dict[str, Any], context: PipelineContext) -> CanonicalContentItem: ...

class Extractor(Protocol):
    name: str
    version: str
    def extract(self, content_item: CanonicalContentItem, context: PipelineContext) -> ExtractedSignals: ...

class Resolver(Protocol):
    name: str
    version: str
    def resolve(self, signals: ExtractedSignals, context: PipelineContext) -> ResolvedSignals: ...

class Enricher(Protocol):
    name: str
    version: str
    def enrich(self, entity: dict[str, Any], context: PipelineContext) -> dict[str, Any]: ...

class Scorer(Protocol):
    name: str
    version: str
    def score(self, entity: dict[str, Any], context: PipelineContext) -> dict[str, Any]: ...

class Publisher(Protocol):
    name: str
    version: str
    def publish(self, payload: dict[str, Any], destination: dict[str, Any], context: PipelineContext) -> None: ...

class ModuleRegistry(Protocol):
    def register_connector(self, connector: SourceConnector) -> None: ...
    def register_normalizer(self, normalizer: Normalizer) -> None: ...
    def register_extractor(self, extractor: Extractor) -> None: ...
    def register_resolver(self, resolver: Resolver) -> None: ...
    def register_enricher(self, enricher: Enricher) -> None: ...
    def register_scorer(self, scorer: Scorer) -> None: ...
    def register_publisher(self, publisher: Publisher) -> None: ...
    def get_connector(self, name: str) -> SourceConnector: ...
    def get_normalizer(self, name: str) -> Normalizer: ...
    def get_extractor(self, name: str) -> Extractor: ...
    def get_resolver(self, name: str) -> Resolver: ...
    def get_enricher(self, name: str) -> Enricher: ...
    def get_scorer(self, name: str) -> Scorer: ...
    def get_publisher(self, name: str) -> Publisher: ...
```

**Contract rules:**
- `fetch()` returns raw records only — no analytics, no alias resolution
- `normalize()` must not discard reference to raw payload; must be deterministic
- `extract()` must record confidence where applicable; must not call publishers
- Extractor/Scorer/Publisher output must be versioned

---

## Canonical Schemas (Pydantic v2)

```python
class EngagementMetrics(BaseModel):
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None

class CanonicalContentItem(BaseModel):
    id: str
    schema_version: str
    source_platform: Literal["youtube", "tiktok", "instagram", "other"]
    source_account_id: str | None = None
    source_account_handle: str | None = None
    source_account_type: Literal["creator", "brand", "retailer", "other"] | None = None
    source_url: str
    external_content_id: str | None = None
    published_at: datetime
    collected_at: datetime
    content_type: Literal["video", "short", "reel", "post", "other"]
    title: str | None = None
    caption: str | None = None
    text_content: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    mentions_raw: list[str] = Field(default_factory=list)
    media_metadata: dict[str, Any] = Field(default_factory=dict)
    engagement: EngagementMetrics = Field(default_factory=EngagementMetrics)
    language: str | None = None
    region: str = "US"
    raw_payload_ref: str
    normalizer_version: str

class EntityMention(BaseModel):
    raw_text: str
    normalized_text: str | None = None
    confidence: float | None = None
    start_char: int | None = None
    end_char: int | None = None

class PriceMention(BaseModel):
    raw_text: str
    currency: str | None = None
    amount: float | None = None
    confidence: float | None = None

class ExtractedSignals(BaseModel):
    content_item_id: str
    schema_version: str
    extractor_version: str
    perfume_mentions: list[EntityMention] = Field(default_factory=list)
    brand_mentions: list[EntityMention] = Field(default_factory=list)
    note_mentions: list[EntityMention] = Field(default_factory=list)
    retailer_mentions: list[EntityMention] = Field(default_factory=list)
    price_mentions: list[PriceMention] = Field(default_factory=list)
    discount_mentions: list[EntityMention] = Field(default_factory=list)
    recommendation_tags: list[str] = Field(default_factory=list)
    sentiment_hints: list[str] = Field(default_factory=list)
    usage_context_tags: list[str] = Field(default_factory=list)
    extraction_metadata: dict[str, Any] = Field(default_factory=dict)

class ResolvedEntityLink(BaseModel):
    entity_type: Literal["perfume", "brand", "retailer", "note"]
    entity_id: str
    canonical_name: str
    matched_from: str
    confidence: float | None = None

class ResolvedSignals(BaseModel):
    content_item_id: str
    resolver_version: str
    resolved_entities: list[ResolvedEntityLink] = Field(default_factory=list)
    unresolved_mentions: list[str] = Field(default_factory=list)
    alias_candidates: list[dict[str, Any]] = Field(default_factory=list)

class PerfumeEntity(BaseModel):
    perfume_id: str
    brand_id: str | None = None
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    concentration: str | None = None
    official_notes: list[str] = Field(default_factory=list)
    family: str | None = None
    status: Literal["active", "discontinued", "unknown"] = "unknown"
    metadata_sources: list[str] = Field(default_factory=list)
    entity_version: str

class PriceSnapshot(BaseModel):
    id: str
    perfume_id: str
    retailer_id: str
    captured_at: datetime
    currency: str = "USD"
    price: float | None = None
    list_price: float | None = None
    availability: Literal["in_stock", "out_of_stock", "unknown"] = "unknown"
    product_url: str
    source_name: str

class DiscountSnapshot(BaseModel):
    id: str
    perfume_id: str
    retailer_id: str
    captured_at: datetime
    discount_type: str | None = None
    discount_value: float | None = None
    promo_text: str | None = None
    product_url: str
    source_name: str

class TrendSignal(BaseModel):
    perfume_id: str
    window: Literal["7d", "30d"]
    mention_count: int
    engagement_weighted_mentions: float
    creator_weighted_mentions: float
    recency_score: float
    novelty_score: float
    trend_score: float
    top_context_tags: list[str] = Field(default_factory=list)
    top_note_mentions: list[str] = Field(default_factory=list)
    scoring_version: str
```

---

## Storage Interfaces

```python
class RawStorage(Protocol):
    def save_raw_batch(self, source_name: str, run_id: str, items: list[dict[str, Any]]) -> list[str]: ...

class NormalizedStorage(Protocol):
    def save_content_items(self, items: list[CanonicalContentItem]) -> None: ...
    def get_content_items(self, ids: list[str]) -> list[CanonicalContentItem]: ...

class SignalStorage(Protocol):
    def save_extracted_signals(self, items: list[ExtractedSignals]) -> None: ...
    def save_resolved_signals(self, items: list[ResolvedSignals]) -> None: ...

class EntityStorage(Protocol):
    def upsert_perfumes(self, items: list[PerfumeEntity]) -> None: ...
    def get_perfume_by_alias(self, alias: str) -> PerfumeEntity | None: ...

class AnalyticsStorage(Protocol):
    def save_trend_signals(self, items: list[TrendSignal]) -> None: ...
    def get_trend_signals(self, window: str) -> list[TrendSignal]: ...
```

**Storage rules:**
- Raw payloads must be persisted **before** normalization results are committed
- Normalized items must reference raw payload location (`raw_payload_ref`)
- Storage must support replay workflows
- Failed items must be traceable to source and run_id

---

## Configuration Structure

### configs/app.yaml
```yaml
app_name: perfume_trend_sdk
environment: dev
schema_version: "1.0"
default_region: US
logging:
  level: INFO
  format: json
storage:
  raw_backend: filesystem
  normalized_backend: sqlite
  signals_backend: sqlite
  entities_backend: sqlite
  analytics_backend: sqlite
workflows:
  ingest_social_content:
    enabled: true
  enrich_market_data:
    enabled: true
  build_weekly_report:
    enabled: true
```

### configs/sources/youtube.yaml (example)
```yaml
name: youtube_watchlist
enabled: true
connector: youtube_connector
normalizer: social_content_normalizer
cursor_strategy: published_after
fetch_limit: 50
watchlist_file: configs/watchlists/creators_us.yaml
rate_limits:
  requests_per_minute: 30
retry:
  max_attempts: 3
  backoff_seconds: 5
```

### configs/watchlists/creators_us.yaml (example)
```yaml
accounts:
  - platform: youtube
    account_handle: "example_creator"
    account_type: creator
    priority: high
    region: US
    active: true
```

### configs/scoring/trend_score.yaml (example)
```yaml
trend_score:
  mention_weight: 1.0
  engagement_weight: 0.5
  creator_weight: 0.8
  recency_weight: 0.7
  novelty_weight: 0.3
creator_weights:
  high: 1.5
  medium: 1.0
  low: 0.7
```

**Lives in config:** active sources, watchlists, fetch params, schedules, scoring weights, output routes, feature flags, account priorities

**Does NOT live in config:** business-critical computations requiring code, complex entity matching algorithms

---

## Workflows

### Workflow A: ingest_social_content
1. Load pipeline context
2. For each enabled social connector:
   - validate config → healthcheck → fetch raw batch → persist raw
   - normalize items → persist canonical content
   - run extractors → persist extracted signals
   - run resolvers → persist resolved signals
   - update cursor
3. Emit workflow summary

### Workflow B: enrich_market_data
1. Load recently resolved perfume entities
2. For each entity: run metadata enricher → price enricher → discount enricher
3. Persist entity updates, price snapshots, discount snapshots
4. Emit enrichment summary

### Workflow C: build_weekly_report
1. Load last 7 days of resolved and enriched data
2. Run scoring modules
3. Aggregate: top perfumes, notes, creators, retailers, discount signals
4. Persist trend signals
5. Publish: JSON + CSV + markdown report + optional Sheets sync

---

## First End-to-End Path (required before multi-source)

```
YouTube watchlist → normalization → extraction → resolution → storage → weekly markdown export
```

Acceptance conditions:
- Source fetch succeeds with cursor support
- Canonical content records are created
- Perfume mentions are extracted from normalized items
- Resolved entities are stored
- Weekly markdown output is generated from stored results

---

## Logging Specification

All runtime logs must be structured JSON with these fields:

```json
{
  "timestamp": "ISO8601",
  "level": "INFO|WARNING|ERROR",
  "run_id": "string",
  "workflow_name": "string",
  "module_type": "connector|normalizer|extractor|...",
  "module_name": "string",
  "event_name": "string",
  "source_name": "string",
  "entity_id": "string (if applicable)",
  "message": "string",
  "error_type": "string (if applicable)"
}
```

---

## Error Handling

### Error Classes
```
ConfigValidationError
ConnectorHealthcheckError
FetchError
NormalizationError
ExtractionError
ResolutionError
EnrichmentError
PublishError
StorageError
```

### Rules
- Connector failure must NOT crash unrelated source workflows
- Item-level normalization errors: log and skip when safe
- Extraction errors: preserve failed content item identifiers
- Publisher failures: must NOT delete analytics results
- Retry only where idempotence is acceptable

### Retry Policy
| Operation | Retry |
|-----------|-------|
| Network fetch | Yes |
| Storage write (idempotent) | Yes |
| Normalization logic bug | No — fail and log |
| Extraction parsing error | No — log for inspection |

---

## Scoring Formula

```
trend_score =
  (mention_count × mention_weight) +
  (engagement_weighted_mentions × engagement_weight) +
  (creator_weighted_mentions × creator_weight) +
  (recency_score × recency_weight) +
  (novelty_score × novelty_weight)
```

- All weights loaded from `configs/scoring/trend_score.yaml`
- Creator tier comes from watchlist metadata (`priority: high/medium/low`)
- Formula must be isolated in scorer module
- Report must display which `scoring_version` was used

---

## Versioning

Required version fields:
- `schema_version` — canonical schema
- `normalizer_version` — normalizer logic
- `extractor_version` — extraction logic
- `resolver_version` — resolution logic
- `scoring_version` — scoring formulas
- `entity_version` — entity shape

**Rule:** Whenever output shape or logic materially changes, the corresponding version must change.
**Replay requirement:** Historical raw data must be replayable through newer versions of normalization, extraction, or scoring.

---

## Security Rules

- Secrets must NOT be hardcoded anywhere in the codebase
- Credentials must come from environment variables or secret manager
- Source configs may reference secret keys by name only
- Logs must NOT expose tokens or session secrets
- Browser automation settings must remain source-isolated

---

## Testing Requirements

### Unit tests (required)
- Config loading
- Connector validation
- Normalizer mapping behavior
- Extractor output shape
- Resolver alias matching
- Scorer formula behavior
- Publisher payload formatting

### Integration tests (required)
- One connector end-to-end through normalization and extraction
- Replay from raw storage
- Weekly report generation from stored data
- Module replacement without breaking registry

### Fixtures (required)
- Raw YouTube-like content item
- Raw Instagram-like content item
- Raw TikTok-like content item
- Ambiguous perfume alias examples
- Price and discount page samples

---

## Module Development Workflow

For every new module, follow this sequence:
1. Define the contract (interface)
2. Create skeleton implementation
3. Create example config
4. Create test cases
5. Register module in registry
6. Run integration
7. Document the interface

---

## Implementation Milestones

| Milestone | Scope |
|-----------|-------|
| 1 | Core skeleton + config loader + registry + logging |
| 2 | YouTube connector + social normalizer + raw/normalized storage |
| 3 | Perfume mention extractor + brand extractor + basic resolver |
| 4 | Weekly markdown report |
| 5 | TikTok and Instagram watchlist connectors |
| 6 | Market enrichment for price and discount signals |
| 7 | Trend scoring + CSV/JSON outputs |
| 8 | SDK cleanup + examples + fixture set |

---

## Implementation Roadmap (Stages)

| Stage | Goal | Status |
|-------|------|--------|
| 0 | Project Charter | Done |
| 1 | Domain Modeling | Done |
| 2 | Core Framework Skeleton | Next → Milestone 1 |
| 3 | First end-to-end pipeline (YouTube) | Milestones 2–4 |
| 4 | Social Source Expansion (TikTok, Instagram) | Milestone 5 |
| 5 | Extraction Engine v1 | Milestone 3 |
| 6 | Identity Resolution Layer | Milestone 3 |
| 7 | Market Enrichment Layer | Milestone 6 |
| 8 | Trend Scoring Engine | Milestone 7 |
| 9 | Reporting & Delivery | Milestones 4, 7 |
| 10 | SDK Packaging | Milestone 8 |
| 11 | Monetization Adapters | Post-v1 |

---

## Definition of Done — v1

- [ ] Minimum 3 sources running
- [ ] Single canonical schema for all v1 sources
- [ ] Perfume mentions extracted and aggregated
- [ ] Notes, prices, and retailers added for at least a subset of entities
- [ ] Weekly report assembled automatically
- [ ] One module can be disabled without breaking the core
- [ ] New connector can be added via template

---

## Scope — v1

**In scope:**
- US market, perfume category
- Watchlist monitoring of known US players
- Level 1: TikTok, Instagram, YouTube watchlists
- Level 2: brand sites, retail pages, price/availability/discount pages
- Normalization, extraction, basic enrichment, trend score, weekly report

**Out of scope for v1:**
- Full TikTok/Instagram/YouTube scan
- Real-time tracking
- Full comment analysis
- Multi-language / multi-region
- Complex recommendation models
- Public SDK for third-party developers

---

## Key Business Questions System Must Answer

1. Which perfumes are currently being promoted in the US by key accounts?
2. Who exactly is promoting them?
3. What exactly are they saying about them?
4. Which notes repeat most often?
5. What price range is being discussed?
6. Where are they sold?
7. Are there signs of discounts, promotions, or commercial pressure?

---

## Implementation Plan v1 — Sprint Breakdown

### Build Philosophy

Build as a sequence of thin, testable vertical slices. Each slice must:
- implement one clear responsibility
- fit the contracts defined in Tech Spec v1
- remain replaceable
- be usable in the next sprint

For each module: define interface → skeleton → minimum logic → tests → integration → document.

---

### Sprint Overview

| Sprint | Goal | Status |
|--------|------|--------|
| 0 | Project bootstrap — repo skeleton, package structure, configs | Done |
| 1 | Core framework — config, registry, logging, models, storage interfaces | Done |
| 2 | First end-to-end source — YouTube → raw → normalize → extract → resolve → markdown | Done |
| 3 | Hybrid AI Intelligence — pre-filter, multi-engine AI extractor, router | Next |
| 3.5 | Source Intelligence — who drives trends, influence scoring, UnifiedSignal extension | Pending |
| 4 | Social expansion — TikTok + Instagram connectors under same contracts | Pending |
| 5 | Intelligence layer — full extraction, resolution, enrichment, scoring | Pending |
| 6 | Output + SDK packaging — CSV/JSON/Sheets publishers, replay, docs, fixtures | Pending |
| 7 | Stabilization — modular review, contract freeze, v1 readiness check | Pending |

---

### Sprint 0 — Project Bootstrap

Exit criteria:
- package structure exists and imports work
- configs load from filesystem path
- pytest runs (even with placeholders)

Files:
```
pyproject.toml, README.md, .env.example
configs/app.yaml, configs/sources/, configs/watchlists/, configs/scoring/
perfume_trend_sdk/__init__.py + all top-level package dirs
tests/ + fixtures/ structure
```

---

### Sprint 1 — Core Framework

Exit criteria:
- foundation modules compile
- config + registry operational
- all core schemas exist
- storage interfaces defined
- core unit tests pass

Modules: `core/config`, `core/registry`, `core/logging`, `core/errors`, `core/models`, `storage/interfaces`

Key files:
```
core/config/models.py          ← AppConfig, LoggingConfig, StorageConfig
core/config/loader.py          ← load_yaml, load_app_config
core/errors/base.py + typed errors
core/logging/logger.py         ← log_event (structured JSON)
core/models/context.py         ← PipelineContext
core/models/fetch.py           ← FetchCursor, FetchSessionResult
core/models/content.py         ← CanonicalContentItem
core/models/signals.py         ← ExtractedSignals, ResolvedSignals
core/models/entities.py        ← PerfumeEntity, PriceSnapshot, DiscountSnapshot
core/models/analytics.py       ← TrendSignal
core/types/contracts.py        ← Protocol interfaces for all module types
core/registry/module_registry.py
storage/interfaces/raw.py + normalized.py + signals.py + entities.py + analytics.py
```

---

### Sprint 2 — First End-to-End Source (YouTube)

Required path before multi-source expansion:
```
YouTube watchlist → raw storage → normalization → extraction → resolution → markdown output
```

Exit criteria:
- fetch returns FetchSessionResult with cursor support
- raw, normalized, extracted, resolved layers all exist in storage
- markdown weekly report generated
- replay from raw manually possible

Key files:
```
connectors/youtube/connector.py + client.py + mappers.py
storage/raw/filesystem.py
normalizers/social_content/normalizer.py
storage/normalized/sqlite_store.py
extractors/perfume_mentions/extractor.py
extractors/brand_mentions/extractor.py
storage/signals/sqlite_store.py
resolvers/perfume_identity/resolver.py + alias_store.py
publishers/markdown/weekly_report.py
workflows/ingest_social_content.py
workflows/build_weekly_report.py
```

---

### Sprint 3 — Hybrid AI Intelligence Layer

**Goal:** Upgrade extraction from rule-based to hybrid AI + multi-engine + source intelligence.

**Architecture:**
```
Fetch → Pre-filter → AI Extractor (via router) → Resolver → Unified Signals → Scoring → Reports
```

**Pipeline rules:**
- Rule-based extractor = fallback (always works without AI)
- AI layer = optional, plugged via router only
- Pipeline must work without AI
- Do NOT hardcode AI logic in pipeline
- All AI engines must return same unified output schema

**Phase A — Pre-filter**
```
extractors/pre_filter/filter.py
```
- Skip non-perfume content before AI call
- Reduce API cost and noise

**Phase B — Multi-Engine AI Extraction**
```
extractors/ai_engines/
    base.py          ← AIExtractor Protocol
    router.py        ← get_extractor(provider: str) -> AIExtractor
    openai_extractor.py
    claude_extractor.py   (placeholder)
    gemini_extractor.py   (placeholder)
```

AI interface:
```python
class AIExtractor(Protocol):
    def extract(self, text: str) -> dict: ...
```

Required unified output schema (ALL engines must return this):
```json
{
  "perfumes": [
    {"brand": "Dior", "product": "Sauvage Elixir", "confidence": 0.95, "sentiment": "positive"}
  ],
  "brands": ["Dior"],
  "notes": ["vanilla", "oud"],
  "sentiment": "positive",
  "confidence": 0.92
}
```

**Phase C — AI Config**
```yaml
ai:
  provider: "openai"
  model: "gpt-4o-mini"
  temperature: 0
  enabled: true
```

**Phase D — Pipeline Integration**
Update: `workflows/test_pipeline.py`, `workflows/ingest_social_content.py`

**Phase E — Cost & Control**
- `max_tokens` config
- Fallback to rule-based extractor on AI failure

**Exit criteria:**
- Pre-filter implemented
- AIExtractor interface defined
- OpenAI extractor working
- Router routes by config provider
- Pipeline works with AI disabled
- Fallback to rule-based confirmed

---

### Sprint 3.5 — Source Intelligence Layer

**Goal:** Identify WHO drives trends and weight their influence.

**Modules:**
```
analysis/source_intelligence/
    analyzer.py
    scoring.py
```

**Output schema:**
```json
{
  "source_type": "influencer | brand | user | bot",
  "influence_score": 0,
  "credibility_score": 0.0,
  "engagement_level": "low | medium | high"
}
```

**UnifiedSignal extension** (`core/models/unified_signal.py`):
- `source_type: str | None`
- `influence_score: float | None`
- `credibility_score: float | None`

**Business value:** System sells influence-weighted intelligence, not raw mention counts.
Example: "80% of Dior hype driven by 3 influencers with >500k audience"

**Exit criteria:**
- Source analyzer classifies source type
- Influence scoring works from metadata
- UnifiedSignal extended with source fields

---

### Sprint 4 — Social Expansion (previously Sprint 3)

Exit criteria:
- TikTok + Instagram connectors conform to same SourceConnector contract
- registry activates source modules by config
- core contracts unchanged

Key files:
```
connectors/tiktok_watchlist/connector.py + client.py + config.py
connectors/instagram_watchlist/connector.py + client.py + config.py
core/config/watchlist_loader.py
configs/watchlists/creators_us.yaml (finalized schema)
```

---

### Sprint 4 — Intelligence Layer

Exit criteria:
- notes, prices, retailers, discounts enter the data model
- brand and perfume aliases resolve from fixtures
- trend scores generated and stored

Key files:
```
extractors/note_mentions/extractor.py
extractors/price_mentions/extractor.py
extractors/retailer_mentions/extractor.py
extractors/recommendation_signals/extractor.py
resolvers/brand_identity/resolver.py
storage/entities/sqlite_store.py
enrichers/perfume_metadata/enricher.py
enrichers/pricing/enricher.py
enrichers/discounts/enricher.py
storage/analytics/sqlite_store.py
scorers/trend_score/scorer.py
scorers/creator_weight/scorer.py
scorers/note_momentum/scorer.py
workflows/enrich_market_data.py
```

---

### Sprint 5 — Output + SDK Packaging

Exit criteria:
- JSON, CSV, optional Sheets outputs available
- replay workflow works
- module template docs exist
- project resembles SDK-ready constructor

Key files:
```
publishers/json/publisher.py
publishers/csv/publisher.py
publishers/sheets/publisher.py (optional)
workflows/replay_from_raw.py
docs/module_contracts/source_connector.md + normalizer.md + extractor.md
sdk/examples/sample_connector.py + sample_extractor.py + sample_publisher.py
tests/fixtures/ (hardened: social, commerce, entities, edge cases)
```

---

### Sprint 6 — Stabilization

Required review checklist:
- YouTube connector swappable without changing extractor logic?
- TikTok connector disableable while report still builds from other sources?
- Raw payloads replayable through newer normalizer versions?
- Scoring weights entirely config-driven?
- Outputs decoupled from internal storage shape?
- New publisher addable without editing connector code?

Exit criteria: all critical integration tests pass, contracts frozen, known limitations documented.

---

### File Build Order Summary

| Phase | Files |
|-------|-------|
| A — Foundation | pyproject.toml, core/config/*, core/errors/*, core/logging/*, core/models/*, core/types/contracts.py, core/registry/module_registry.py, storage/interfaces/* |
| B — First vertical slice | connectors/youtube/*, storage/raw/filesystem.py, normalizers/social_content/normalizer.py, storage/normalized/sqlite_store.py, extractors/perfume_mentions/*, extractors/brand_mentions/*, storage/signals/sqlite_store.py, resolvers/perfume_identity/*, workflows/ingest_social_content.py, publishers/markdown/weekly_report.py, workflows/build_weekly_report.py |
| C — Source expansion | connectors/tiktok_watchlist/*, connectors/instagram_watchlist/*, core/config/watchlist_loader.py |
| D — Intelligence | extractors/note_mentions→recommendation_signals/*, resolvers/brand_identity/*, storage/entities/*, enrichers/*/*, storage/analytics/*, scorers/*/*, workflows/enrich_market_data.py |
| E — Packaging | publishers/json→sheets/*, workflows/replay_from_raw.py, docs/module_contracts/*, sdk/examples/*, tests/fixtures/* |

---

## Perfume Trend Intelligence Engine v1

### 1. Product Definition

Perfume Trend Intelligence Engine is a market terminal for fragrance trends.

**This is NOT:**
- a static dashboard
- a reporting tool
- a simple analytics panel

**This IS:**
- a real-time trend intelligence system
- a decision engine
- a market-like environment, where perfumes, brands, notes, and accords behave like tradable entities (similar to stocks/assets)

The system must allow users to:
- detect rising trends early
- monitor momentum
- compare entities
- identify breakouts and reversals
- understand WHY something is moving

---

### 2. Core Product Metaphor

All tracked entities behave like market instruments.

Each entity has:
- score (like price)
- momentum
- volume
- volatility
- signals

UI and backend must follow this model strictly.

---

### 3. Core Entities

**Primary**
- Brand
- Perfume
- Note
- Accord

**Secondary**
- Creator (TikTok / YouTube / etc.)
- Channel (TikTok, YouTube, Google Trends, etc.)
- Retailer (Amazon, etc.)
- Signal Event

---

### 4. Existing Data (DO NOT REMOVE)

The system already includes:
- `mention_count` (weighted float)
- `influence_score` weighting
- sentiment multiplier: positive → ×1.2, negative → ×0.5
- `ai_confidence` multiplier
- `trend_score`
- `mentions_last_24h`
- `mentions_prev_24h`
- `growth`

These must remain intact. All new layers must build on top of this, not replace it.

---

### 5. Required Backend Architecture (Market Engine)

**Layer A — Ingestion**

Collect data from:
- YouTube (metadata)
- Google Trends
- Reddit
- News / blogs
- Fragrance datasets (GitHub / Kaggle)
- Keepa API (Amazon proxy)

**Layer B — Entity Resolution**
- detect brands, perfumes, notes, accords
- resolve aliases and misspellings
- map mentions → entities

**Layer C — Enrichment**
- sentiment
- confidence
- influence score
- engagement normalization
- channel attribution
- region attribution

**Layer D — Aggregation**

Store time-bucketed data:
- hourly (short-term)
- daily (core)
- weekly/monthly (long-term)

**Layer E — Derived Metrics**

Compute:
- `composite_market_score`
- momentum
- acceleration
- volatility
- source_diversity
- creator_velocity
- saturation_risk
- forecast_score

**Layer F — Signal Engine**

Detect:
- breakout
- acceleration spike
- reversal
- divergence
- creator-driven spike
- cross-channel confirmation
- note fatigue

**Layer G — Serving Layer**

Expose API endpoints for UI:
- dashboard
- screener
- entity page
- charts
- signals
- watchlists
- alerts

---

### 6. Data Model Requirements

**Required new fields**

Each entity must have:
- `entity_id`
- `entity_type`
- `ticker` (short symbol)

Time series must include:
- `timestamp`
- `mention_count`
- `unique_authors`
- `engagement_sum`
- `sentiment_avg`
- `search_index`
- `retailer_score`
- `composite_market_score`
- `acceleration`
- `volatility`
- `forecast_score`

---

### 7. UI Principles (MANDATORY)

UI must follow financial terminal logic, not ecommerce.

**Required characteristics:**
- dark theme
- data-dense layout
- real-time feel
- chart-first design
- comparison-friendly
- sortable tables
- filters everywhere

**Avoid:**
- "beauty brand" UI
- decorative layouts
- large empty spaces
- marketing-style pages

The UI must feel like TradingView or a simplified Bloomberg terminal.

---

### 8. API Design Principles

APIs must return:
- precomputed data
- chart-ready time series
- screener-ready rows

Frontend must NOT:
- compute metrics from raw mentions
- aggregate heavy datasets

All heavy computation belongs to backend.

---

### 9. Data Source Policy

**Allowed sources:**
- Google Trends
- YouTube metadata
- Reddit
- News / blogs
- Fragrance datasets (GitHub / Kaggle)
- Keepa API (Amazon data proxy)

**Amazon Policy:**
- Use Keepa API for: price history, rank proxy, stock proxy
- DO NOT use Amazon Seller / SP-API
- DO NOT require seller account authentication

---

### 10. Development Rules

- DO NOT delete existing pipeline
- ALWAYS extend current system
- EACH feature must map to: entity, metric, signal, workflow

**Prefer:**
- precomputation
- normalized data
- reusable metrics

**Avoid:**
- one-off scripts
- UI-specific logic in backend
- raw data exposure

---

### 11. V1 Scope (STRICT PRIORITY)

Build in this order:
1. Entity master tables (brands, perfumes, notes, accords)
2. Time-series storage
3. Composite market score
4. Dashboard API
5. Top movers table
6. Screener API
7. Entity page (summary + chart)
8. Signal detection v1
9. Watchlists

---

### 12. V2 Scope

After V1:
- Notes & accords rotation engine
- Relationship graph
- Channel attribution layer
- Creator influence system
- Saturation detection
- Forecast engine

---

### 13. Product Goal

The system must allow users to feel:
- they are watching a live market
- they can discover trends early
- data is actionable
- movement is visible and explainable

This is NOT about data display. This is about decision advantage.

---

### 14. Golden Rule

If a feature does not:
- improve trend detection
- improve decision speed
- improve signal clarity

→ it should NOT be implemented.

---

## 15. Frontend Terminal Architecture (V1)

The frontend for Perfume Trend Intelligence Engine must be implemented as a **desktop-first market terminal**, not as a marketing site or ecommerce storefront.

### Frontend goals

The frontend must:

* render dense market intelligence clearly
* support fast scanning of movers, signals, and entities
* prioritize dashboard, screener, and entity workflows
* remain compatible with future watchlists, alerts, and compare features

### Core frontend stack

Preferred stack:

* Next.js
* React
* TypeScript
* Tailwind CSS
* TanStack Query
* Zustand
* TanStack Table
* Recharts for V1 charts

The stack may be adapted to the existing repo if needed, but the architecture and interaction model must remain consistent.

### Frontend page structure

Required V1 routes:

* `/dashboard`
* `/screener`
* `/entities/[entityId]`
* `/watchlists` (placeholder allowed in V1)
* `/alerts` (placeholder allowed in V1)

The root route may redirect to `/dashboard`.

### App shell rules

The app must use a shared terminal shell with:

* left sidebar
* top navigation/header
* main content region

Sidebar items:

* Dashboard
* Screener
* Watchlists
* Alerts

The shell must be:

* dark-first
* compact
* desktop-first
* route-aware with active state highlighting

### Primary UI pages

#### Dashboard

The dashboard must include:

* top control bar
* KPI strip
* top movers table
* main chart panel
* signal feed panel

The dashboard is the market overview screen and should answer:

* what is moving?
* how strongly is it moving?
* what just triggered?

#### Entity page

The entity page must include:

* entity header
* main chart
* metrics rail
* signal timeline
* recent mentions

The entity page should answer:

* what is happening?
* how strong is it?
* why is it happening?
* what should the user watch next?

#### Screener

The screener must include:

* quick controls
* advanced filters
* sortable results table
* pagination footer

The screener is the discovery workflow and should allow users to hunt for opportunities quickly.

### Watchlists and alerts

In V1:

* watchlists and alerts may exist as scaffold or placeholder routes
* do not build full workflow unless explicitly requested
* preserve route structure so the product can expand cleanly later

### Shared design system requirements

All frontend work must use a consistent terminal-style design system.

Required shared primitives:

* TerminalPanel
* SectionHeader
* KpiCard
* MetricBadge
* DeltaBadge
* SignalBadge
* EmptyState
* ErrorState
* LoadingSkeleton
* ControlBar
* SearchInput
* FilterChip
* ChartContainer

Design principles:

* information first
* dense but readable
* semantic color only
* consistent formatting across all pages

### Table rules

Tables are core UI infrastructure.

Use a reusable table system for:

* top movers
* screener
* watchlists later
* alerts later

Tables must support:

* compact density
* sortable headers
* row click
* loading state
* empty state

### Chart rules

Charts must be used as analytical tools, not decoration.

V1 charts should:

* use line charts
* support time range switching where practical
* use real backend timeseries
* prioritize clarity over animation

### API integration rules

Frontend must consume real backend APIs where available.

Do:

* centralize API calls in a dedicated API layer
* use typed response models
* use TanStack Query for server-state
* keep server data out of local UI stores

Do not:

* fetch directly in deeply nested presentational components
* scatter formatting logic across pages
* hardcode fake market data when real endpoints exist

### State management rules

Use:

* TanStack Query for server state
* Zustand only for local UI state

Examples of local UI state:

* selected dashboard entity
* modal open/close
* screener panel open/close
* active watchlist id later
* chart mode toggle

Do not use a large global store for backend responses.

### URL and filter behavior

Screener filters should be URL-friendly where practical.

Examples:

* entity type
* signal type
* min score
* min confidence
* min mentions
* sort_by
* order
* offset

This ensures shareable and reproducible views.

### Formatting rules

Use a shared adapter/formatter layer for:

* score formatting
* growth formatting
* confidence formatting
* signal labels
* timestamps

Do not duplicate formatting logic across components.

### Frontend build order

When implementing the frontend, build in this order:

1. app shell
2. shared primitives
3. dashboard page
4. entity page
5. screener page
6. watchlists placeholder
7. alerts placeholder

### Frontend non-goals for V1

Do not prioritize:

* landing page
* auth system
* ecommerce-style branding
* animation-heavy UI
* full compare mode
* full watchlist workflow
* full alerts workflow

### Golden frontend rule

If a frontend change does not improve:

* market readability
* decision speed
* signal clarity
* workflow efficiency

then it should not be prioritized.

---

## 16. Frontend/Backend Contract Rules

The frontend must treat the backend as the source of truth for:

* market scores
* growth rates
* confidence
* signals
* timeseries
* screener filtering results

### Rules

* do not recompute backend market metrics in the frontend
* do not derive alternative signal logic in the frontend
* only format and present backend values
* keep frontend adapters lightweight and presentation-focused

### Page-to-endpoint mapping

* Dashboard → `/api/v1/dashboard`
* Screener → `/api/v1/screener`
* Entity Page → `/api/v1/entities/{id}`
* Signals feed → `/api/v1/signals`

### Contract principle

If payload shape mismatches UI needs:

* prefer lightweight frontend adapters first
* only change backend when the mismatch is structural or repeated

---

## 17. Current Product Stage

The project is currently in the transition from backend foundation to frontend terminal implementation.

This means:

* backend market engine is already functional
* API payloads are terminal-ready for V1
* frontend work should now focus on dashboard, entity page, and screener
* watchlists and alerts remain secondary in the first frontend build pass

---

## 18. Watchlists and Alerts (V1)

The next product layer after the core terminal is a personal monitoring workflow built around watchlists and alerts.

### Watchlists goals

Watchlists allow users to:

* save important entities
* group them into named lists
* return quickly to a curated set of perfumes and brands
* monitor signal activity without re-running searches

### Alerts goals

Alerts allow users to:

* be notified when meaningful entity changes happen
* react to breakouts, acceleration, and threshold changes
* reduce the need to manually check the terminal repeatedly

### V1 watchlists scope

Implement only:

* manual watchlists
* add/remove entities
* watchlist detail view with enriched market fields
* watchlist activity based on signals affecting watched entities

Do not implement yet:

* team/shared watchlists
* dynamic screener-based watchlists
* folders/tags
* complex notes system

### V1 alerts scope

Implement only:

* entity-based alerts
* in-app delivery only
* active/paused state
* trigger history
* cooldown support
* simple condition types

Do not implement yet:

* email/slack delivery
* team notification routing
* screener-wide alerts
* boolean rule builders
* AI-generated alert conditions

### V1 alert condition types

Allowed V1 conditions:

* breakout_detected
* acceleration_detected
* any_new_signal
* score_above
* growth_above
* confidence_below

### Watchlist and alert principle

This layer must transform the terminal from a place users visit occasionally into a place they can rely on continuously.

---

## 19. Alerting Rules

Alerts must be low-noise and meaningful.

### Rules

* the backend is the source of truth for alert evaluation
* the frontend must never independently evaluate alert conditions
* alerts should only trigger on explicit backend-supported conditions
* every alert type must map to clear stored logic
* repeated alerts require cooldown protection

### Cooldown

Every alert must support a cooldown window.
Default V1 behavior should use a 24-hour cooldown unless explicitly configured otherwise.

If a condition remains true during the cooldown period:

* do not generate a fresh active alert event
* optionally record a suppressed event for diagnostics later

### Alert quality principle

It is better to deliver fewer, more meaningful alerts than many repetitive alerts.
A noisy alert system reduces trust in the product.

---

## 20. Current Product Direction

The project has now moved from:

* backend market engine foundation
* terminal frontend foundation
  into:
* monitoring and retention workflow

Current product priority:

1. core terminal stability
2. watchlists
3. alerts
4. later deployment and live ingestion hardening

The next implementation work should focus on turning analytics into persistent user workflows.

---

