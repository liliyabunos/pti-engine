# Perfume Trend Intelligence SDK

Modular platform for collecting, normalizing, analyzing, and packaging perfume trend signals from the US market.

## Architecture Layers

- **connectors** — fetch raw data from external sources (YouTube, TikTok, Instagram, retail)
- **normalizers** — convert raw source data into canonical content objects
- **extractors** — extract perfume, brand, note, price, and retailer mentions from content
- **scorers** — compute trend scores and signal aggregations
- **publishers** — deliver outputs to JSON, CSV, Markdown, Google Sheets
- **workflows** — orchestrate pipeline stages end-to-end

## Project Status

v1 in active development. See CLAUDE.md for full architecture specification and sprint plan.
