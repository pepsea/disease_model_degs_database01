"""パス設定と解析の既定パラメータ。

`data/` が正のデータ、`build/` は ingest が生成する派生物。環境変数で
両者の場所を差し替えられるようにしてあり、テストが一時ディレクトリを
指すために利用する。
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default


def data_dir() -> Path:
    return _env_path("DMDEG_DATA_DIR", ROOT_DIR / "data")


def build_dir() -> Path:
    return _env_path("DMDEG_BUILD_DIR", ROOT_DIR / "build")


def expression_dir() -> Path:
    return data_dir() / "expression"


def degs_dir() -> Path:
    return data_dir() / "degs"


def vocab_dir() -> Path:
    return data_dir() / "vocab"


def parquet_dir() -> Path:
    return build_dir() / "parquet"


def expression_parquet_dir() -> Path:
    return parquet_dir() / "expression"


def duckdb_path() -> Path:
    return build_dir() / "dmdeg.duckdb"


def manifest_path() -> Path:
    return build_dir() / "manifest.json"


# 解析の既定値
DEFAULT_TOP_VARIABLE_GENES = 2000
PSEUDOCOUNT = 1.0

# 発現マトリクスとして受理する拡張子。GEO 由来のファイルは tsv.gz が多い。
EXPRESSION_SUFFIXES = (".csv", ".csv.gz", ".tsv", ".tsv.gz", ".txt", ".txt.gz")

# 発現値の単位。正規化処理がこの値で分岐するため統制必須。
UNITS = ("counts", "tpm", "fpkm", "log2_intensity")

# 発現マトリクスの gene_id の種類。
GENE_ID_TYPES = ("symbol", "ensembl", "entrez")

# 重複 gene_id の集約方法。
DUPLICATE_POLICIES = ("max", "sum", "mean", "first")
