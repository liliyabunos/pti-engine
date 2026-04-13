from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


SUPPORTED_SUFFIXES = {".csv", ".json", ".jsonl"}


def normalize_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_gender(value: Optional[str]) -> str:
    raw = normalize_text(value).lower()
    if not raw:
        return ""
    if raw in {"women", "woman", "female", "for women", "feminine"}:
        return "women"
    if raw in {"men", "man", "male", "for men", "masculine"}:
        return "men"
    if raw in {"unisex", "shared", "unisexual"}:
        return "unisex"
    return raw


def normalize_year(value: Optional[str]) -> str:
    raw = normalize_text(value)
    if not raw:
        return ""
    try:
        year = int(float(raw))
    except (TypeError, ValueError):
        return ""
    if 1800 <= year <= 2100:
        return str(year)
    return ""


def pick_first(row: Dict[str, Any], candidates: List[str]) -> str:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for candidate in candidates:
        value = lowered.get(candidate.lower())
        text = normalize_text(value)
        if text:
            return text
    return ""


def combine_name_fields(brand_name: str, perfume_name: str) -> Tuple[str, str]:
    """
    Clean very common bad mappings:
    - If perfume_name already starts with brand, keep it as perfume_name
    - Do not duplicate brand in canonical seed columns
    """
    brand = normalize_text(brand_name)
    perfume = normalize_text(perfume_name)
    return brand, perfume


def iter_csv_rows(path: Path) -> Iterable[Dict[str, Any]]:
    for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            for row in rows:
                yield dict(row)
            return
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not decode %s with any supported encoding" % path)


def iter_json_rows(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item
        return

    if isinstance(payload, dict):
        for key in ("items", "data", "rows", "results", "perfumes", "fragrances"):
            value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        yield item
                return

    raise ValueError("Unsupported JSON structure for fragrance seed build")


def iter_jsonl_rows(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                yield item


def iter_rows(path: Path) -> Iterable[Dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return iter_csv_rows(path)
    if suffix == ".json":
        return iter_json_rows(path)
    if suffix == ".jsonl":
        return iter_jsonl_rows(path)
    raise ValueError("Unsupported file format: %s" % suffix)


def resolve_input_file(input_path: Optional[str], raw_dir: Path) -> Path:
    if input_path:
        path = Path(input_path)
        if not path.exists():
            raise FileNotFoundError("Input file not found: %s" % path)
        return path

    candidates = []
    for path in raw_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            candidates.append(path)

    if not candidates:
        raise FileNotFoundError(
            "No raw fragrance dataset found in %s" % raw_dir
        )

    if len(candidates) > 1:
        print("Found multiple candidate raw files:")
        for item in candidates:
            print(" - %s" % item)
        raise RuntimeError(
            "Multiple raw files found. Pass --input explicitly."
        )

    return candidates[0]


def map_row_to_seed(row: Dict[str, Any], source_name: str, row_index: int) -> Optional[Dict[str, str]]:
    brand_name = pick_first(
        row,
        [
            "brand_name",
            "brand",
            "designer",
            "house",
            "maker",
            "brand title",
        ],
    )

    perfume_name = pick_first(
        row,
        [
            "perfume_name",
            "perfume",
            "name",
            "title",
            "fragrance",
            "product_name",
            "fragrance_name",
        ],
    )

    release_year = pick_first(
        row,
        [
            "release_year",
            "year",
            "launch_year",
            "launched",
            "release date",
        ],
    )

    gender = pick_first(
        row,
        [
            "gender",
            "target_gender",
            "sex",
            "audience",
        ],
    )

    brand_name, perfume_name = combine_name_fields(brand_name, perfume_name)

    if not brand_name or not perfume_name:
        return None

    return {
        "fragrance_id": "fd_%07d" % row_index,
        "brand_name": brand_name,
        "perfume_name": perfume_name,
        "release_year": normalize_year(release_year),
        "gender": normalize_gender(gender),
        "source": source_name,
    }


def build_seed(
    input_file: Path,
    output_file: Path,
    source_name: str,
) -> int:
    seen = set()
    rows_out: List[Dict[str, str]] = []

    for index, row in enumerate(iter_rows(input_file), start=1):
        mapped = map_row_to_seed(row, source_name=source_name, row_index=index)
        if mapped is None:
            continue

        dedupe_key = (
            mapped["brand_name"].strip().lower(),
            mapped["perfume_name"].strip().lower(),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        rows_out.append(mapped)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "fragrance_id",
                "brand_name",
                "perfume_name",
                "release_year",
                "gender",
                "source",
            ],
        )
        writer.writeheader()
        writer.writerows(rows_out)

    return len(rows_out)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build internal fragrance seed CSV from raw Fragrance-Database dataset."
    )
    parser.add_argument(
        "--input",
        required=False,
        help="Path to raw fragrance dataset (.csv, .json, .jsonl). If omitted, auto-detects inside data/fragrance_master/raw/",
    )
    parser.add_argument(
        "--output",
        default="perfume_trend_sdk/data/fragrance_master/seed_master.csv",
        help="Output internal seed CSV path",
    )
    parser.add_argument(
        "--raw-dir",
        default="perfume_trend_sdk/data/fragrance_master/raw",
        help="Directory used for raw dataset auto-discovery",
    )
    parser.add_argument(
        "--source-name",
        default="fragrance_database",
        help="Source label written into seed rows",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir)
    input_file = resolve_input_file(args.input, raw_dir)
    output_file = Path(args.output)

    count = build_seed(
        input_file=input_file,
        output_file=output_file,
        source_name=args.source_name,
    )

    print("raw input:", input_file)
    print("seed output:", output_file)
    print("seed rows written:", count)


if __name__ == "__main__":
    main()
