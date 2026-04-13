# PTI Market Terminal — Frontend Notes (V1)

## Running Locally

```bash
cd frontend
cp .env.example .env.local   # set NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm install
npm run dev                  # starts on http://localhost:3000
```

Backend must be running on port 8000. See backend README for setup.

## Stack

| Concern | Library |
|---------|---------|
| Framework | Next.js 16 App Router |
| Styling | Tailwind CSS v4 |
| Server state | TanStack Query v5 |
| Tables | TanStack Table v8 |
| Charts | Recharts |
| Local state | Zustand v5 |
| Icons | Lucide React |

## Pages

| Route | Status | Backend endpoint |
|-------|--------|-----------------|
| `/dashboard` | ✅ Live | `GET /api/v1/dashboard` |
| `/screener` | ✅ Live | `GET /api/v1/screener` |
| `/entities/[entityId]` | ✅ Live | `GET /api/v1/entities/{id}` |
| `/watchlists` | 🚧 Scaffold | — |
| `/alerts` | 🚧 Scaffold | — |

## V1 Known Limitations

### Screener text search is client-side only
The `SearchInput` in the screener control bar filters `data.rows` in the
browser after the backend returns the current page. It does **not** send a
search parameter to the backend. Search is therefore limited to the current
page (50 results by default).

**Fix path:** Add a `q` / `search` parameter to `GET /api/v1/screener`.

### Watchlists and alerts are scaffold only
`/watchlists` and `/alerts` exist as placeholder routes with navigation
links and "soon" labels. No watchlist or alert backend API exists yet.

### Compare mode is a placeholder
The "Related Entities & Compare Mode" block on entity pages is non-functional.
It preserves the product layout direction only.

### Recent mention links depend on backend URL quality
`RecentMentions` renders an external link only when `source_url` starts with
`http`. Records with internal IDs or null URLs show a lock icon (`internal`).
URL quality depends on the ingestion pipeline's `source_url` storage.

### Brand analytics may be shallower than perfume analytics
Brand-level entities aggregate across all child perfumes. Signal density,
timeseries depth, and confidence scores may be lower for brand entities
than for specific perfume entities.

### Entity page navigation uses browser history
The Back button on `/entities/[entityId]` calls `router.back()`. If the user
navigates directly to a deep link (no history), the back button has no effect.

## Design System

All shared primitives live in `src/components/primitives/`. Import them via
the barrel export in `src/components/primitives/index.ts`.

All display formatting (scores, growth rates, timestamps, signal labels) goes
through `src/lib/formatters/index.ts`. Never duplicate formatting logic in
components.

## State Rules

- **TanStack Query** → all server state (dashboard, screener, entity detail)
- **Zustand** (`src/lib/stores/ui.ts`) → local UI state only:
  - `selectedEntityId` — dashboard selected mover
  - `screenerFiltersOpen` — (legacy, now unused; screener manages locally)
  - `chartMetric` — entity page chart metric toggle
- **URL search params** → screener filter/sort/pagination state (shareable links)
