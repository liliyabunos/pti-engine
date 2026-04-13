from pathlib import Path

from perfume_trend_sdk.workflows.load_fragrance_master import ingest_seed_csv
from perfume_trend_sdk.storage.entities.fragrance_master_store import FragranceMasterStore


def test_ingest_seed_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "seed.csv"
    db_path = tmp_path / "pti.sqlite"

    csv_path.write_text(
        "\n".join(
            [
                "fragrance_id,brand_name,perfume_name,release_year,gender,source",
                "fr_001,Parfums de Marly,Delina,2017,women,kaggle",
                "fr_002,Maison Francis Kurkdjian,Baccarat Rouge 540,2015,unisex,kaggle",
            ]
        ),
        encoding="utf-8",
    )

    ingest_seed_csv(csv_path, db_path)

    store = FragranceMasterStore(str(db_path))
    assert store.count_rows("brands") == 2
    assert store.count_rows("perfumes") == 2
    assert store.count_rows("fragrance_master") == 2

    delina_aliases = store.get_perfume_aliases("parfums de marly delina")
    assert "delina" in delina_aliases
    assert "pdm delina" in delina_aliases
    assert "parfums de marly delina" in delina_aliases


def test_ingest_is_idempotent_for_same_seed(tmp_path: Path) -> None:
    csv_path = tmp_path / "seed.csv"
    db_path = tmp_path / "pti.sqlite"

    csv_path.write_text(
        "\n".join(
            [
                "fragrance_id,brand_name,perfume_name,release_year,gender,source",
                "fr_001,Parfums de Marly,Delina,2017,women,kaggle",
            ]
        ),
        encoding="utf-8",
    )

    ingest_seed_csv(csv_path, db_path)
    ingest_seed_csv(csv_path, db_path)

    store = FragranceMasterStore(str(db_path))
    assert store.count_rows("brands") == 1
    assert store.count_rows("perfumes") == 1
    assert store.count_rows("fragrance_master") == 1
