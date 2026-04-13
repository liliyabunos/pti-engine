# Perfume Trend Intelligence Engine — V1 Review Package

**Product:** PTI Market Terminal  
**Build:** V1 (internal review / stakeholder demo)  
**Status:** Functional end-to-end on dev data  
**Date:** April 2026

---

## Table of Contents

1. [What This Is](#1-what-this-is)
2. [V1 Implementation Status](#2-v1-implementation-status)
3. [Local Runbook](#3-local-runbook)
4. [Demo Walkthrough](#4-demo-walkthrough)
5. [Dataset Transparency](#5-dataset-transparency)
6. [Architecture Summary](#6-architecture-summary)
7. [V1 Known Limitations](#7-v1-known-limitations)
8. [Screenshot Checklist](#8-screenshot-checklist)
9. [What Comes Next](#9-what-comes-next)

---

## 1. What This Is

**Perfume Trend Intelligence Engine** is a market terminal for fragrance trends.

It tracks perfumes, brands, notes, and accords the way a trading terminal tracks assets — with scores, momentum, signals, and timeseries. It is built for fragrance brands, retail buyers, and content strategists who need to understand what is moving, why it is moving, and how fast.

### Core workflows (V1)

| Workflow | Description |
|----------|-------------|
| **Dashboard** | Real-time market overview — KPI strip, top movers ranked by composite score, center entity chart, signal feed |
| **Entity Page** | Deep dive on a single perfume or brand — market score chart, metrics rail, signal timeline, recent mention sources |
| **Screener** | Filterable, sortable table of all tracked entities — filter by entity type, signal type, score threshold, momentum; URL-synced params; preset views |

### What it is not
- Not a social feed or CMS
- Not an ecommerce storefront
- Not a reporting static dashboard
- Not a full production system (dev data, not live ingestion)

---

## 2. V1 Implementation Status

### Backend

| Component | Status | Notes |
|-----------|--------|-------|
| Fragrance master / seed catalog | ✅ | CSV-sourced, seeded into `brands` + `perfumes` tables |
| Entity resolution (alias matching) | ✅ | Fuzzy + exact match via `pti.db` resolver |
| Bridge / identity mapping | ✅ | `sync_identity_map.py` links resolver IDs to market engine UUIDs |
| Dev mention backfill | ✅ | Synthetic but realistic — 3-day mention history for ~8 entities |
| Daily aggregation job | ✅ | `aggregate_daily_market_metrics.py` produces timeseries + signals |
| Composite market score | ✅ | Engagement-weighted, confidence-multiplied, trend-scored |
| Momentum / acceleration / volatility | ✅ | Derived from rolling window comparisons |
| Signal detection (breakout, accel spike, reversal, new entry) | ✅ | `BreakoutDetector` fires on score thresholds |
| FastAPI market engine API | ✅ | All V1 endpoints live on port 8000 |
| API health check | ✅ | `GET /healthz` |

### API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/dashboard` | Top movers, KPIs, recent signals, breakouts |
| `GET /api/v1/screener` | Filterable entity table with pagination |
| `GET /api/v1/entities` | All tracked entities |
| `GET /api/v1/entities/{id}` | Entity detail: summary, timeseries, signals, mentions |
| `GET /api/v1/signals` | Recent signal feed |
| `GET /healthz` | API liveness check |
| `GET /docs` | Interactive Swagger UI |

### Frontend

| Page / Component | Status | Notes |
|-----------------|--------|-------|
| App shell (StatusBar, Sidebar, Header) | ✅ | Desktop-first terminal layout |
| Dashboard page | ✅ | KPIs, 3-col grid, entity chart, signal feed |
| Entity page | ✅ | Header, chart + metric toggles, metrics rail, signal timeline, mentions |
| Screener page | ✅ | Sortable table, URL-synced filters, preset views, filter sidebar |
| Shared primitives (13 components) | ✅ | TerminalPanel, SectionHeader, KpiCard, DeltaBadge, SignalBadge, etc. |
| Shared formatters | ✅ | All display values go through `src/lib/formatters/index.ts` |
| Watchlists page | 🚧 Scaffold | Route exists, no backend |
| Alerts page | 🚧 Scaffold | Route exists, no backend |

---

## 3. Local Runbook

### Prerequisites

- Python 3.11+
- Node.js 18+ and npm
- No external API keys required for the review build (dev data only)

### 3.1 Clone and install

```bash
git clone <repo-url>
cd Perfume_Trend_Intelligence_SDK

# Python deps
pip install -e .
```

### 3.2 Environment variables

```bash
cp .env.example .env
# For dev/review: no API keys needed.
# The market engine uses outputs/market_dev.db by default (SQLite).
# Optionally set:
# PTI_DB_PATH=outputs/market_dev.db   (already default)
```

### 3.3 Build the dev database (one-time setup)

Run these steps **in order** if starting from scratch. If `outputs/market_dev.db` already exists with data, skip to step 3.4.

```bash
# Step 1 — Seed the fragrance catalog (brands + perfumes from CSV)
python scripts/seed_market_catalog.py

# Step 2 — Sync identity maps from resolver DB to market engine DB
python scripts/sync_identity_map.py

# Step 3 — Backfill 3 days of synthetic mention data
python scripts/dev_backfill_mentions.py

# Step 4 — Run the daily aggregation job (builds timeseries + signals)
python -m perfume_trend_sdk.jobs.aggregate_daily_market_metrics

# Verify: should print entity count and signal count
```

> **Which DB is authoritative for this review:**  
> `outputs/market_dev.db` — this is the market engine database the API reads from.  
> `outputs/pti.db` — the legacy resolver database (used by bridge scripts; not read by the API directly).

### 3.4 Start the backend API

```bash
uvicorn perfume_trend_sdk.api.main:app --reload --port 8000
```

Verify:
- `http://localhost:8000/healthz` → `{"status": "ok"}`
- `http://localhost:8000/docs` → Swagger UI with all endpoints

### 3.5 Start the frontend

```bash
cd frontend
cp .env.example .env.local
# .env.local already contains: NEXT_PUBLIC_API_BASE_URL=http://localhost:8000

npm install
npm run dev
```

Frontend runs at: **http://localhost:3000**

The app auto-redirects to `/dashboard`.

### 3.6 Quick verification

Open `http://localhost:3000` and check:
- [ ] StatusBar shows green "API live" dot
- [ ] Dashboard KPI strip loads with entity counts
- [ ] Top Movers table shows rows
- [ ] Clicking a mover row updates the center chart
- [ ] Screener loads and shows filterable results

---

## 4. Demo Walkthrough

### Recommended review path (~10 minutes)

#### Step 1 — Dashboard overview

Open `http://localhost:3000/dashboard`

- Read the **KPI strip** at the top: tracked brands, tracked perfumes, active movers, breakout signals today, avg market score
- Scan the **Top Movers table** (left column): ranked by composite market score, amber tickers, signal badges
- Notice the **center chart panel**: currently shows the first entity automatically
- Look at the **signal feed** (right column): recent signals with strength scores

#### Step 2 — Select a mover

Click any row in the Top Movers table.

- The **center chart updates** immediately — the line chart shows 30 days of composite market score + mention count overlay
- The **mini-header** above the chart shows: ticker, name, current score, growth badge, signal badge
- The **stat row** below the chart shows: score, mentions, confidence, momentum, Δscore, as-of date

#### Step 3 — Try preset filter chips

On the dashboard control bar, the search input filters the movers list by name or ticker in real time.

#### Step 4 — Open the Entity page

Click the **↗ arrow link** in the chart mini-header, or Cmd+click an entity name in the table.

On the entity page:
- **Header**: ticker, type pill, signal badge, name, brand; large market score, growth rate badge, mention count, confidence; disabled "Watch" and "Alert" buttons (placeholders)
- **Chart** (main, left): 30-day line chart. Toggle between Score / Mentions / Momentum using the buttons above the chart. The average reference line shows context.
- **Metrics rail** (right): three sections — Market (score, growth, mentions, confidence), Momentum (momentum, acceleration, volatility), Signals (latest signal type, strength, total count)
- **Signal Timeline** (below left): newest-first list of detected signals — type, strength, confidence, timestamp
- **Recent Mentions** (below right): source platform, author (when available), engagement count, link or "internal" indicator
- **Compare placeholder** (bottom): non-functional, marks the product direction

Use the **Back** button to return (uses browser history — works from Dashboard or Screener).

#### Step 5 — Open the Screener

Navigate to **Screener** in the sidebar.

- Default view: sorted by Score descending, all entity types
- **Preset chips** in the control bar: try "Breakouts" — filters the table to entities with breakout signals
- **Search**: type a perfume or brand name to filter within current page results
- **Filter sidebar**: click the "Filters" button (top right) to open the sidebar with type chips, signal chips, sort options, min score / min confidence sliders, min mentions input
- **Sortable headers**: click any column header (Score, Growth, Mentions, Momentum, etc.) to sort; click again to reverse direction
- **Pagination footer**: "Showing 1–50 of N" with ← → controls
- **URL sync**: filter changes are reflected in the browser URL — links are shareable and preserve filter state
- **Row click**: clicking any row navigates to that entity's page

#### Step 6 — Open an entity from the Screener

Click any row in the Screener results table to open that entity's detail page. Use Back to return to the filtered screener view (URL state is preserved).

---

## 5. Dataset Transparency

### What is in the dev database

| Data | Source | Notes |
|------|--------|-------|
| Fragrance catalog (brands, perfumes) | CSV seed (`fragrance_master/seed_master.csv`) | Real brand and perfume names from Fragrantica-sourced dataset |
| Identity maps | `sync_identity_map.py` | Slug-matched from resolver DB to market engine UUIDs |
| Mention records | `dev_backfill_mentions.py` | **Synthetic** — realistic but fake engagement data, not from live APIs |
| Daily timeseries | `aggregate_daily_market_metrics.py` | Computed from synthetic mentions — mathematically real derivations on fake input |
| Market signals | `aggregate_daily_market_metrics.py` | Breakout/acceleration/reversal detection runs on synthetic timeseries |

### What this means

- **Entity names, tickers, and catalog data are real.** The brands and perfumes shown are real products.
- **Engagement numbers, mention counts, and scores are synthetic.** They are designed to exercise the system (realistic variance, escalating volume for some entities to trigger signals), not to represent actual market activity.
- **Signal detection is real logic on synthetic input.** The `BreakoutDetector`, momentum calculations, and confidence scoring all run correctly — they just process dev-generated data, not live ingestion.
- **Recent mention source URLs:** Most dev mentions will show "internal" (no public URL) because the backfill script does not create real source URLs. This is expected. Real ingestion paths produce real YouTube/TikTok URLs.
- **Do not interpret the rankings or scores as real market intelligence.** The demo data is designed to make the system look good and behave correctly, not to accurately represent the current fragrance market.

### For a production review
The system is designed to run against live ingestion data. The pipeline paths (YouTube connector → normalization → extraction → resolution → aggregation) are implemented. What is missing for production is: live API keys, scheduled pipeline runs, and a production deployment (PostgreSQL + cloud hosting). See Section 9.

---

## 6. Architecture Summary

```
┌─────────────────────────────────────────────────────────┐
│  Data Sources                                           │
│  YouTube · TikTok · Reddit · Fragrantica               │
└─────────────────────────┬───────────────────────────────┘
                          │ raw content
                          ▼
┌─────────────────────────────────────────────────────────┐
│  Ingestion Pipeline (connectors → normalizers →         │
│  extractors → resolvers)                                │
│                                                         │
│  outputs/normalized.db   ← canonical content items     │
│  outputs/pti.db          ← resolved entity signals     │
└─────────────────────────┬───────────────────────────────┘
                          │ resolved signals + metadata
                          ▼
┌─────────────────────────────────────────────────────────┐
│  Bridge / Identity Mapping Layer                        │
│  scripts/sync_identity_map.py                          │
│                                                         │
│  Maps resolver Integer PKs → market engine UUID PKs    │
│  brand_identity_map · perfume_identity_map             │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  Market Engine (outputs/market_dev.db)                  │
│                                                         │
│  brands · perfumes · entity_mentions                   │
│  daily_market_snapshots · market_signals               │
│  brand_identity_map · perfume_identity_map             │
│                                                         │
│  Aggregation: aggregate_daily_market_metrics.py        │
│    → composite_market_score (engagement × confidence)  │
│    → momentum / acceleration / volatility              │
│    → signal detection (breakout, accel spike, etc.)    │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  API Layer (FastAPI · port 8000)                        │
│                                                         │
│  GET /api/v1/dashboard    → top movers + KPIs          │
│  GET /api/v1/screener     → filterable entity table    │
│  GET /api/v1/entities/{id} → detail + timeseries       │
│  GET /api/v1/signals       → signal feed               │
│  GET /healthz              → liveness                  │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  Frontend Terminal (Next.js · port 3000)                │
│                                                         │
│  Dashboard · Entity Page · Screener                    │
│  TanStack Query · Recharts · TanStack Table            │
│  Zustand (local UI state) · URL params (screener)      │
└─────────────────────────────────────────────────────────┘
```

### Key design decisions

| Decision | Rationale |
|----------|-----------|
| SQLite for dev | Zero-setup, file-portable. PostgreSQL-ready via `DATABASE_URL` env var. |
| Composite market score computed server-side | Frontend never recomputes metrics — it only formats and presents backend values. |
| Bridge layer (identity map) | Separates the resolver (older Integer-PK system) from the market engine (UUID-based). Allows both systems to evolve independently. |
| URL-synced screener filters | Screener views are shareable. Browser back/forward preserves filter state. |
| Synthetic dev data | Enables full system testing and demo without live API keys or real ingestion runs. |

---

## 7. V1 Known Limitations

### Functional limitations

| Limitation | Impact | Fix path |
|-----------|--------|---------|
| Screener text search is client-side, current page only | Search covers ≤50 rows (current page), not the full dataset | Add `q` / `search` param to `GET /api/v1/screener` |
| Watchlists are placeholder only | "Watch" button on entity page is disabled; `/watchlists` route is scaffold | Implement watchlist API + frontend |
| Alerts are placeholder only | "Alert" button on entity page is disabled; `/alerts` route is scaffold | Implement alert API + frontend |
| Compare mode is placeholder | Entity page shows a non-functional compare block | Implement compare API + side-by-side view |
| Entity page back uses `router.back()` | On direct deep links (no history), back button has no effect | Use explicit `/dashboard` or `/screener` links with state context |
| Recent mention source URLs | Most dev mentions show "internal" lock icon (no public URL) | Real ingestion pipelines store real YouTube/TikTok URLs |

### Data limitations (dev build)

| Limitation | Impact |
|-----------|--------|
| Synthetic mention data | Scores and rankings are not real market intelligence |
| ~3 days of timeseries per entity | Charts show a short history; in production, history grows continuously |
| ~8-10 active entities | Dashboard shows a small universe; production will cover hundreds |
| Brand-level analytics may be lighter | Brand entities aggregate fewer mentions than top perfumes in dev data |

### Architecture limitations (pre-production)

| Limitation | Impact |
|-----------|--------|
| No scheduled ingestion | Data does not update automatically; aggregation must be re-run manually |
| SQLite in dev | Not suitable for concurrent production load |
| No authentication | API has no auth; CORS is open (`*`) |
| No deployment story | No docker-compose, no CI/CD, no cloud config yet |

---

## 8. Screenshot Checklist

For a demo recording or slide deck, capture these screens:

### Core pages
- [ ] Dashboard full page — KPI strip visible, Top Movers table, center chart, signal feed
- [ ] Dashboard with a row selected — amber left-edge accent on mover row, chart updated with entity name in mini-header
- [ ] Entity page full page — header with score + growth, chart with metric toggle, metrics rail visible
- [ ] Entity page signal timeline — newest-first signal list with type labels and strength values
- [ ] Screener full page — sorted table, all column headers visible
- [ ] Screener with Breakouts preset active — filter chip highlighted, table filtered to breakout signals

### Interaction states
- [ ] Screener filter sidebar open — sidebar with Type / Signal / Sort / Min Score slider visible
- [ ] Screener URL bar showing filter params (e.g. `?signal_type=breakout&sort_by=composite_market_score`)
- [ ] Entity page chart with "Momentum" metric selected — sky-blue line
- [ ] Dashboard entity chart with stat row showing score / mentions / delta

### Shell
- [ ] Sidebar in expanded state (lg+ width) — PTI monogram, nav items with active amber accent
- [ ] StatusBar with green API dot visible

---

## 9. What Comes Next

### Immediate (V1 polish + completeness)
- Watchlists — save entities to named lists, quick-access from sidebar
- Alerts — set threshold triggers on score / momentum; surface in feed
- Compare mode — side-by-side entity chart comparison
- Backend text search for screener

### Near-term (V1.5)
- Live ingestion scheduling (cron or GitHub Actions)
- PostgreSQL migration + production deployment config (docker-compose)
- Note & accord analytics (notes rising/falling, note momentum tracking)
- Creator attribution layer (which accounts drive which entities)

### Medium-term (V2)
- Forecast score / early trend detection
- Saturation risk indicator
- Relationship graph (brand → perfumes, notes → accords)
- Public API / data export

---

*For questions about the codebase, see `CLAUDE.md` (full architecture spec) and `frontend/FRONTEND_NOTES.md` (frontend-specific notes).*
