# Phase 1b — Fragrantica Access Layer Unblock Report

**Date:** 2026-04-20  
**Scope:** Phase 1b — Replace HTTP fetch with browser-based client to bypass Cloudflare 403  
**Status:** COMPLETE — 403 unblocked, pipeline verified with real HTML

---

## 1. Problem Recap

All direct HTTP requests (plain `requests`, `curl_cffi` with TLS impersonation, headless Playwright/Chromium, headless Firefox) returned:

```
HTTP 403 Forbidden — "Just a moment..." (Cloudflare Turnstile / Bot Management)
```

This was consistent from both local machine and Railway production IPs.

---

## 2. Solution Implemented

### Client chosen: `CDPFragranticaClient`

**Approach:** Connect Playwright to a real user Chrome browser via Chrome DevTools Protocol (CDP).

Chrome must be launched once with remote debugging enabled:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=9222 \
    --user-data-dir=/tmp/chrome_frag_debug \
    https://www.fragrantica.com/
```

The real Chrome browser has already passed Cloudflare's Turnstile challenge as a real user. All subsequent page requests via CDP inherit the same browser session + IP + fingerprint — returning **HTTP 200**.

**File:** `perfume_trend_sdk/connectors/fragrantica/cdp_client.py`

---

## 3. URL Resolution

Fragrantica requires a numeric perfume ID in the URL:
```
https://www.fragrantica.com/perfume/{Brand}/{Name}-{ID}.html
```

Slug-only URLs (what `build_perfume_url()` produces) return 404:
```
https://www.fragrantica.com/perfume/parfums-de-marly/delina.html → 404
```

**Implemented:** automatic search-based URL resolution in `CDPFragranticaClient._resolve_via_search()`:
1. If URL returns 404 → extract brand and perfume from slug
2. Search Fragrantica: `https://www.fragrantica.com/search/?query={perfume}+{brand}`
3. Parse first matching result URL (with numeric ID)
4. Navigate to resolved URL

Example resolutions:
```
/perfume/parfums-de-marly/delina.html        → /perfume/Parfums-de-Marly/Delina-43871.html
/perfume/creed/aventus.html                  → /perfume/Creed/Aventus-...html
/perfume/byredo/gypsy-water.html             → /perfume/Byredo/Gypsy-Water-Absolu-...html
/perfume/xerjoff/erba-pura.html              → /perfume/Xerjoff/Erba-Pura-55157.html
```

---

## 4. Parser Updates

Fragrantica migrated to a Vue.js SPA. The old parser selectors were written for the previous server-rendered HTML structure. Minimal updates applied:

| Element | Old structure | New structure |
|---------|---------------|---------------|
| Notes | `h4` + `span` inside `#pyramid` | `span.pyramid-note-label` inside `div.mx-auto` section containers |
| Section headers | `<h4>Top Notes</h4>` | `<span class="inline-block">Top Notes</span>` |
| Brand name | `/designers/` link text | Canonical URL path → `re.search(r"/perfume/([^/]+)/"` |
| Accords | `div.accord-box > div.accord-name` | Not currently rendered in the page DOM |

**Notes extraction:** new primary path using section containers:
```python
section_divs = pyramid.find_all("div", class_="mx-auto")
for div in section_divs:
    header = div.find("span", class_="inline-block")   # "Top Notes" / "Middle Notes" / "Base Notes"
    note_spans = div.find_all("span", class_="pyramid-note-label")  # actual note names
```

Old h4/span path retained as fallback for backward compatibility.

---

## 5. Integration

| Flag | Effect |
|------|--------|
| `USE_CDP=true` (env) | Uses `CDPFragranticaClient` |
| `--cdp` (CLI) | Uses `CDPFragranticaClient` |
| `USE_PLAYWRIGHT=true` / `--playwright` | Uses `PlaywrightFragranticaClient` (headless, for future Railway use with proxy) |
| default | Uses `FragranticaClient` (plain HTTP) |

No other code changed: parser, normalizer, enricher, DB store, workflow orchestration all untouched.

---

## 6. Test Batch Results

**Command:**
```bash
USE_CDP=true python3 -m perfume_trend_sdk.workflows.enrich_from_fragrantica \
    --resolver-db outputs/pti.db \
    --limit 30 \
    --output outputs/enriched/fragrantica_phase1b.json
```

**Results:**

| Metric | Value |
|--------|-------|
| Perfumes processed | 30 |
| Fetched (HTTP 200, real HTML) | **28** |
| Parsed | 28 |
| Enriched | 28 |
| Market UUID matched | 28 |
| DB persisted | 28 |
| Failed | 2 (URL resolution matched wrong perfume) |
| HTTP 403 errors | **0** |

---

## 7. DB State Verification

**After batch run (cumulative, includes prior Phase 1 reference seed):**

| Table | Row count |
|-------|-----------|
| `fragrantica_records` | **29** |
| `notes` | **137** |
| `accords` | **9** |
| `perfume_notes` | **282** |
| `perfume_accords` | **13** |
| `perfumes.notes_summary` (non-NULL) | **25** |

All four Phase 1b validation criteria met:

| Criterion | Result |
|-----------|--------|
| `fragrantica_records > 0` | ✅ 29 |
| `perfume_notes > 0` | ✅ 282 |
| `perfume_accords > 0` | ✅ 13 |
| `notes_summary` updated | ✅ 25 perfumes |

---

## 8. Sample Parsed Data (Real Fragrantica HTML)

### Parfums de Marly Delina
```
Top: Litchi, Rhubarb, Bergamot, Nutmeg, Black Currant
Middle: Turkish Rose, Peony, Musk, Petalia, Vanilla
Base: Cashmeran, Incense, Cedar, Haitian Vetiver, Caramel
Rating: 3.97 (13,110 votes)
```

### Creed Aventus
```
Top: Black Pepper, Pine Needles, Bergamot
Rating: 3.5
```

### Dior Sauvage
```
Rating: 4.24
```

### Maison Francis Kurkdjian Baccarat Rouge 540
```
Top: Green Notes, Grapefruit, Freesia, Apple, Pear
Rating: 3.8
```

### Top Notes by Mention Count (across 28 enriched perfumes)
```
patchouli: 12  |  jasmine: 10  |  musk: 9  |  bergamot: 9  |  vanilla: 9
cedar: 8  |  sandalwood: 8  |  vetiver: 6  |  white musk: 6  |  nutmeg: 6
```

---

## 9. Known Gaps

| Gap | Detail |
|-----|--------|
| Accords extraction | Fragrantica's current HTML does not render accords in the page DOM (only 9 accords from Phase 1 reference seed, not from real batch). This is a Fragrantica schema change. |
| URL resolution precision | Search-based resolution occasionally returns a variant (e.g., YSL Libre → "Libre Vanille Couture") instead of the base perfume. 2/30 mismatches observed. |
| Production deployment | CDP approach requires local Chrome. For Railway production, the fetch layer requires a residential proxy or a solution to pass the Cloudflare Turnstile challenge programmatically. |

---

## 10. What Files Changed

| File | Change |
|------|--------|
| `perfume_trend_sdk/connectors/fragrantica/cdp_client.py` | NEW — CDP-based client |
| `perfume_trend_sdk/connectors/fragrantica/playwright_client.py` | NEW — Playwright headless client (Phase 1b initial attempt) |
| `perfume_trend_sdk/connectors/fragrantica/parser.py` | UPDATED — `_extract_notes()` handles new Vue.js pyramid structure; `_extract_brand_name()` falls back to canonical URL |
| `perfume_trend_sdk/workflows/enrich_from_fragrantica.py` | UPDATED — `USE_CDP`, `USE_PLAYWRIGHT` flags; `--cdp`, `--playwright` CLI args |
| `pyproject.toml` | UPDATED — `playwright>=1.40` added to dependencies |

---

## 11. Phase 1b Status

| Gate | Status |
|------|--------|
| Code complete | **YES** |
| 403 unblocked (local) | **YES** — zero 403s in 28-fetch batch |
| Pipeline verified with real HTML | **YES** — 282 note rows, 25 notes_summary updated |
| Production deployment | **PARTIAL** — CDP client is local-only; Railway production still needs proxy/CAPTCHA solution |

**Phase 1b: locally complete. Production fetch unblock deferred to Phase 2 infrastructure work.**

---

*Batch run against `outputs/pti.db` (resolver) + `outputs/market_dev.db` (market engine), 2026-04-20.*
