# Fragrance Master Data

This directory contains the static fragrance knowledge base used as the primary source of truth for entity resolution.

## Source

- Kaggle fragrance datasets
- GitHub open fragrance databases
- Manually curated entries

## Format

CSV with the following columns:

| Column | Description |
|---|---|
| `fragrance_id` | Unique identifier |
| `brand_name` | Canonical brand name |
| `perfume_name` | Canonical perfume name |
| `canonical_name` | Full canonical name (brand + perfume) |
| `normalized_name` | Lowercased, cleaned name for matching |
| `release_year` | Release year (optional) |
| `gender` | Target gender: male / female / unisex (optional) |
| `source` | Data source (e.g. kaggle) |

## Rules

- This dataset is **read-mostly** — do not overwrite with runtime pipeline data
- Must be loaded before any extraction/resolution pipeline runs
- Updates must be explicit and versioned
- See `load_fragrance_master.py` for loading logic
