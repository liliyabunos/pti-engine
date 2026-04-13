from pathlib import Path

from perfume_trend_sdk.workflows.load_fragrance_master import ingest_seed_csv
from perfume_trend_sdk.resolvers.perfume_identity.perfume_resolver import PerfumeResolver


def test_resolver_basic(tmp_path: Path):
    csv_path = tmp_path / "seed.csv"
    db_path = tmp_path / "db.sqlite"

    csv_path.write_text(
        "fragrance_id,brand_name,perfume_name,source\n"
        "fr_1,Parfums de Marly,Delina,kaggle\n"
    )

    ingest_seed_csv(csv_path, db_path)

    resolver = PerfumeResolver(str(db_path))

    matches = resolver.resolve_text("best delina perfume review")

    assert len(matches) > 0
    assert matches[0]["canonical_name"] == "Parfums de Marly Delina"
