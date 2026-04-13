from __future__ import annotations

import subprocess
from pathlib import Path


DATASET = "nandini1999/perfume-recommendation-dataset"
OUTPUT_DIR = Path("perfume_trend_sdk/data/fragrance_master/raw")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Downloading dataset from Kaggle...")

    subprocess.run(
        [
            "kaggle",
            "datasets",
            "download",
            "-d",
            DATASET,
            "-p",
            str(OUTPUT_DIR),
            "--unzip",
        ],
        check=True,
    )

    print("Download complete:", OUTPUT_DIR)


if __name__ == "__main__":
    main()
