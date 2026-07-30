"""Parquet 上のクエリ層。

DuckDB を「CSV から生成した parquet に対する検索エンジン」として使う。
キュレーターがこの層に触ることはない。

正規化の SQL 式は `_NORM_EXPR` に一本化してある。遺伝子ごとの発現量取得と
高変動遺伝子の選定で別々の正規化がかかると結果が食い違うため。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Sequence

import duckdb
import pandas as pd

from . import config

_MASTER_VIEWS: dict[str, list[tuple[str, str]]] = {
    "models": [
        ("model_id", "VARCHAR"),
        ("model_name", "VARCHAR"),
        ("species", "VARCHAR"),
        ("modality", "VARCHAR"),
        ("disease_category", "VARCHAR"),
        ("strain", "VARCHAR"),
        ("target_gene", "VARCHAR"),
        ("description", "VARCHAR"),
        ("reference_url", "VARCHAR"),
    ],
    "datasets": [
        ("dataset_id", "VARCHAR"),
        ("title", "VARCHAR"),
        ("model_id", "VARCHAR"),
        ("species", "VARCHAR"),
        ("assay", "VARCHAR"),
        ("unit", "VARCHAR"),
        ("gene_id_type", "VARCHAR"),
        ("platform", "VARCHAR"),
        ("duplicate_policy", "VARCHAR"),
        ("pmid", "VARCHAR"),
        ("geo_url", "VARCHAR"),
        ("submitted_by", "VARCHAR"),
        ("notes", "VARCHAR"),
    ],
    "samples": [
        ("sample_id", "VARCHAR"),
        ("dataset_id", "VARCHAR"),
        ("model_id", "VARCHAR"),
        ("group_label", "VARCHAR"),
        ("genotype", "VARCHAR"),
        ("is_control", "BOOLEAN"),
        ("organ", "VARCHAR"),
        ("tissue_detail", "VARCHAR"),
        ("sex", "VARCHAR"),
        ("age_weeks", "DOUBLE"),
        ("treatment", "VARCHAR"),
        ("replicate", "VARCHAR"),
        ("batch", "VARCHAR"),
        ("library_size", "DOUBLE"),
        ("detected_genes", "BIGINT"),
    ],
    "comparisons": [
        ("comparison_id", "VARCHAR"),
        ("dataset_id", "VARCHAR"),
        ("case_group_label", "VARCHAR"),
        ("control_group_label", "VARCHAR"),
        ("organ", "VARCHAR"),
        ("method", "VARCHAR"),
        ("label", "VARCHAR"),
    ],
    "degs": [
        ("comparison_id", "VARCHAR"),
        ("gene_id", "VARCHAR"),
        ("log2fc", "DOUBLE"),
        ("pvalue", "DOUBLE"),
        ("padj", "DOUBLE"),
        ("base_mean", "DOUBLE"),
    ],
    "genes": [
        ("gene_id", "VARCHAR"),
        ("symbol", "VARCHAR"),
        ("name", "VARCHAR"),
        ("species", "VARCHAR"),
        ("ensembl", "VARCHAR"),
        ("entrez", "VARCHAR"),
        ("biotype", "VARCHAR"),
        ("synonyms", "VARCHAR"),
        ("search_key", "VARCHAR"),
        ("symbol_key", "VARCHAR"),
    ],
}

_EXPRESSION_COLUMNS = [
    ("gene_id", "VARCHAR"),
    ("sample_id", "VARCHAR"),
    ("value", "FLOAT"),
    ("dataset_id", "VARCHAR"),
]

# counts のみ CPM 換算する。tpm/fpkm/log2_intensity は登録値をそのまま使う。
_NORM_EXPR = """
CASE WHEN d.unit = 'counts' AND s.library_size > 0
     THEN e.value / s.library_size * 1000000
     ELSE e.value END
"""


def _sql_literal(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def _empty_view_sql(columns: Sequence[tuple[str, str]]) -> str:
    cols = ", ".join(f"NULL::{sql_type} AS {name}" for name, sql_type in columns)
    return f"SELECT {cols} WHERE FALSE"


def create_views(con: duckdb.DuckDBPyConnection) -> None:
    """`build/parquet/` の各ファイルに VIEW を張る。

    ファイルが無い場合も列と型を持つ空 VIEW を作る。データ未登録の状態でも
    アプリが同じクエリで動くようにするため。
    """
    base = config.parquet_dir()
    for name, columns in _MASTER_VIEWS.items():
        path = base / f"{name}.parquet"
        if path.exists():
            body = f"SELECT * FROM read_parquet({_sql_literal(path)})"
        else:
            body = _empty_view_sql(columns)
        con.execute(f"CREATE OR REPLACE VIEW {name} AS {body}")

    parts = sorted(config.expression_parquet_dir().glob("*/part.parquet"))
    if parts:
        pattern = config.expression_parquet_dir() / "*" / "part.parquet"
        body = (
            "SELECT gene_id, sample_id, value, dataset_id FROM read_parquet("
            f"{_sql_literal(pattern)}, hive_partitioning = 1)"
        )
    else:
        body = _empty_view_sql(_EXPRESSION_COLUMNS)
    con.execute(f"CREATE OR REPLACE VIEW expression AS {body}")


class Store:
    """読み取り専用のクエリ層。

    parquet を参照する VIEW をインメモリ DuckDB に張るだけなので、
    `build/` を作り直したら `reload()` を呼べば最新を読む。
    """

    def __init__(self) -> None:
        self.con = duckdb.connect(":memory:")
        create_views(self.con)
        self._manifest_mtime = self._current_manifest_mtime()

    # ---- 基盤 -------------------------------------------------------

    def _current_manifest_mtime(self) -> float | None:
        path = config.manifest_path()
        return path.stat().st_mtime if path.exists() else None

    def reload(self) -> None:
        create_views(self.con)
        self._manifest_mtime = self._current_manifest_mtime()

    def reload_if_stale(self) -> None:
        """ingest が走った後に自動で最新の parquet を読み直す。"""
        if self._current_manifest_mtime() != self._manifest_mtime:
            self.reload()

    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        cursor = self.con.execute(sql, params) if params else self.con.execute(sql)
        return cursor.fetch_df()

    def manifest(self) -> dict:
        path = config.manifest_path()
        if not path.exists():
            return {
                "generated_at": None,
                "counts": {},
                "datasets": {},
                "issues": [],
                "message": "まだ ingest が実行されていません。`python -m dmdeg.ingest` を実行してください。",
            }
        return json.loads(path.read_text(encoding="utf-8"))

    # ---- カタログ ---------------------------------------------------

    def list_models(self) -> pd.DataFrame:
        return self.query(
            """
            SELECT m.*,
                   COUNT(DISTINCT d.dataset_id) AS n_datasets,
                   COUNT(DISTINCT s.sample_id)  AS n_samples
            FROM models m
            LEFT JOIN datasets d ON d.model_id = m.model_id
            LEFT JOIN samples  s ON s.model_id = m.model_id
            GROUP BY ALL
            ORDER BY m.disease_category, m.model_name
            """
        )

    def list_datasets(
        self,
        species: str | None = None,
        model_id: str | None = None,
        organ: str | None = None,
        disease_category: str | None = None,
        assay: str | None = None,
        q: str | None = None,
    ) -> pd.DataFrame:
        return self.query(
            """
            WITH organ_agg AS (
                SELECT dataset_id,
                       list_sort(list_distinct(list(organ)))       AS organs,
                       list_sort(list_distinct(list(group_label))) AS groups,
                       COUNT(*)::BIGINT                                    AS n_samples,
                       SUM(CASE WHEN is_control THEN 1 ELSE 0 END)::BIGINT AS n_controls
                FROM samples GROUP BY dataset_id
            )
            SELECT d.*, m.model_name, m.disease_category, m.modality,
                   COALESCE(o.n_samples, 0)  AS n_samples,
                   COALESCE(o.n_controls, 0) AS n_controls,
                   o.organs, o.groups
            FROM datasets d
            LEFT JOIN models m   ON m.model_id = d.model_id
            LEFT JOIN organ_agg o ON o.dataset_id = d.dataset_id
            WHERE ($species IS NULL OR d.species = $species)
              AND ($model_id IS NULL OR d.model_id = $model_id)
              AND ($assay IS NULL OR d.assay = $assay)
              AND ($disease_category IS NULL OR m.disease_category = $disease_category)
              AND ($organ IS NULL OR list_contains(o.organs, $organ))
              AND ($q IS NULL OR lower(d.title) LIKE '%' || lower($q) || '%'
                              OR lower(d.dataset_id) LIKE '%' || lower($q) || '%'
                              OR lower(COALESCE(m.model_name, '')) LIKE '%' || lower($q) || '%')
            ORDER BY d.dataset_id
            """,
            {
                "species": species,
                "model_id": model_id,
                "organ": organ,
                "disease_category": disease_category,
                "assay": assay,
                "q": q,
            },
        )

    def get_dataset(self, dataset_id: str) -> dict | None:
        df = self.query(
            """
            SELECT d.*, m.model_name, m.disease_category, m.modality, m.strain, m.target_gene
            FROM datasets d LEFT JOIN models m ON m.model_id = d.model_id
            WHERE d.dataset_id = $dataset_id
            """,
            {"dataset_id": dataset_id},
        )
        if df.empty:
            return None
        return df.iloc[0].to_dict()

    def list_samples(
        self,
        dataset_id: str | None = None,
        organ: str | None = None,
        genotype: str | None = None,
        model_id: str | None = None,
    ) -> pd.DataFrame:
        return self.query(
            """
            SELECT s.*, d.unit, d.assay, m.model_name, m.disease_category
            FROM samples s
            LEFT JOIN datasets d ON d.dataset_id = s.dataset_id
            LEFT JOIN models   m ON m.model_id  = s.model_id
            WHERE ($dataset_id IS NULL OR s.dataset_id = $dataset_id)
              AND ($organ IS NULL OR s.organ = $organ)
              AND ($genotype IS NULL OR s.genotype = $genotype)
              AND ($model_id IS NULL OR s.model_id = $model_id)
            ORDER BY s.dataset_id, s.organ, s.group_label, s.sample_id
            """,
            {"dataset_id": dataset_id, "organ": organ, "genotype": genotype, "model_id": model_id},
        )

    def distinct_values(self, column: str) -> list[str]:
        allowed = {"organ", "genotype", "group_label", "sex", "treatment", "batch"}
        if column not in allowed:
            raise ValueError(f"未対応の列です: {column}")
        df = self.query(
            f"SELECT DISTINCT {column} AS v FROM samples WHERE {column} IS NOT NULL ORDER BY v"
        )
        return df["v"].tolist()

    def facets(self) -> dict[str, list]:
        """ブラウズ画面のファセット選択肢をまとめて返す。"""
        species = self.query("SELECT DISTINCT species AS v FROM datasets WHERE species IS NOT NULL ORDER BY v")
        assays = self.query("SELECT DISTINCT assay AS v FROM datasets WHERE assay IS NOT NULL ORDER BY v")
        categories = self.query(
            "SELECT DISTINCT disease_category AS v FROM models WHERE disease_category IS NOT NULL ORDER BY v"
        )
        modality = self.query("SELECT DISTINCT modality AS v FROM models WHERE modality IS NOT NULL ORDER BY v")
        return {
            "species": species["v"].tolist(),
            "assays": assays["v"].tolist(),
            "disease_categories": categories["v"].tolist(),
            "modalities": modality["v"].tolist(),
            "organs": self.distinct_values("organ"),
            "genotypes": self.distinct_values("genotype"),
        }

    def list_comparisons(self, dataset_id: str | None = None) -> pd.DataFrame:
        return self.query(
            """
            SELECT c.*, d.title AS dataset_title,
                   EXISTS (SELECT 1 FROM degs g WHERE g.comparison_id = c.comparison_id) AS has_deg_table
            FROM comparisons c
            LEFT JOIN datasets d ON d.dataset_id = c.dataset_id
            WHERE ($dataset_id IS NULL OR c.dataset_id = $dataset_id)
            ORDER BY c.comparison_id
            """,
            {"dataset_id": dataset_id},
        )

    def get_degs(self, comparison_id: str) -> pd.DataFrame:
        return self.query(
            """
            SELECT g.*, COALESCE(ge.symbol, g.gene_id) AS symbol
            FROM degs g LEFT JOIN genes ge ON ge.gene_id = g.gene_id
            WHERE g.comparison_id = $comparison_id
            ORDER BY COALESCE(g.padj, g.pvalue, 1), abs(g.log2fc) DESC
            """,
            {"comparison_id": comparison_id},
        )

    # ---- 遺伝子 -----------------------------------------------------

    def search_genes(self, q: str, species: str | None = None, limit: int = 30) -> pd.DataFrame:
        """gene_id / symbol / 同義語の前方一致を優先して返す。"""
        return self.query(
            """
            SELECT gene_id, symbol, name, species, biotype,
                   CASE WHEN search_key = lower($q) OR symbol_key = lower($q) THEN 0
                        WHEN search_key LIKE lower($q) || '%' OR symbol_key LIKE lower($q) || '%' THEN 1
                        ELSE 2 END AS rank
            FROM genes
            WHERE ($species IS NULL OR species IS NULL OR species = $species)
              AND (search_key LIKE '%' || lower($q) || '%'
                   OR symbol_key LIKE '%' || lower($q) || '%'
                   OR lower(COALESCE(synonyms, '')) LIKE '%' || lower($q) || '%')
            ORDER BY rank, length(gene_id), gene_id
            LIMIT $limit
            """,
            {"q": q, "species": species, "limit": limit},
        )

    def gene_expression(
        self,
        gene: str,
        dataset_id: str | None = None,
        organ: str | None = None,
    ) -> pd.DataFrame:
        """1 遺伝子の発現量をサンプル属性つきで返す（群別プロット用）。"""
        return self.query(
            f"""
            SELECT e.gene_id, e.sample_id, e.value AS raw_value,
                   {_NORM_EXPR} AS value,
                   s.dataset_id, s.organ, s.group_label, s.genotype, s.is_control,
                   s.sex, s.age_weeks, s.treatment, s.batch,
                   d.unit, d.assay, d.title AS dataset_title,
                   m.model_id, m.model_name, m.disease_category
            FROM expression e
            JOIN samples  s ON s.sample_id  = e.sample_id
            JOIN datasets d ON d.dataset_id = s.dataset_id
            LEFT JOIN models m ON m.model_id = s.model_id
            WHERE lower(e.gene_id) = lower($gene)
              AND ($dataset_id IS NULL OR s.dataset_id = $dataset_id)
              AND ($organ IS NULL OR s.organ = $organ)
            ORDER BY s.dataset_id, s.organ, s.group_label, s.sample_id
            """,
            {"gene": gene, "dataset_id": dataset_id, "organ": organ},
        )

    def top_variable_genes(self, sample_ids: Sequence[str], limit: int) -> list[str]:
        """指定サンプル集合での高変動遺伝子を SQL 側で選ぶ。

        全遺伝子 × 全サンプルを Python に取り出さずに済ませるための集約。
        ランキングにしか使わないので log の底は問わない。
        """
        if not sample_ids:
            return []
        df = self.query(
            f"""
            WITH sel AS (
                SELECT e.gene_id, ln({_NORM_EXPR} + 1) AS v
                FROM expression e
                JOIN samples  s ON s.sample_id  = e.sample_id
                JOIN datasets d ON d.dataset_id = s.dataset_id
                WHERE e.sample_id IN (SELECT unnest($sample_ids))
            )
            SELECT gene_id FROM sel
            GROUP BY gene_id
            HAVING COUNT(*) > 1
            ORDER BY var_pop(v) DESC NULLS LAST, gene_id
            LIMIT $limit
            """,
            {"sample_ids": list(sample_ids), "limit": int(limit)},
        )
        return df["gene_id"].tolist()

    def matrix(self, sample_ids: Sequence[str], gene_ids: Sequence[str] | None = None) -> pd.DataFrame:
        """遺伝子 × サンプルの正規化済みマトリクスを返す。"""
        if not sample_ids:
            return pd.DataFrame()
        params: dict[str, Any] = {"sample_ids": list(sample_ids)}
        gene_filter = ""
        if gene_ids is not None:
            if not gene_ids:
                return pd.DataFrame()
            gene_filter = "AND e.gene_id IN (SELECT unnest($gene_ids))"
            params["gene_ids"] = list(gene_ids)
        long = self.query(
            f"""
            SELECT e.gene_id, e.sample_id, {_NORM_EXPR} AS value
            FROM expression e
            JOIN samples  s ON s.sample_id  = e.sample_id
            JOIN datasets d ON d.dataset_id = s.dataset_id
            WHERE e.sample_id IN (SELECT unnest($sample_ids)) {gene_filter}
            """,
            params,
        )
        if long.empty:
            return pd.DataFrame()
        wide = long.pivot(index="gene_id", columns="sample_id", values="value")
        # 要求順を保つ（欠損サンプルは列として残さない）
        ordered = [s for s in sample_ids if s in wide.columns]
        return wide[ordered]

    # ---- サンプル選択の解決 -----------------------------------------

    def resolve_samples(
        self,
        sample_ids: Sequence[str] | None = None,
        dataset_id: str | None = None,
        group_label: str | None = None,
        organ: str | None = None,
        genotype: str | None = None,
        is_control: bool | None = None,
    ) -> pd.DataFrame:
        """比較ビルダーの選択条件を実サンプル行に解決する。"""
        return self.query(
            """
            SELECT s.*, d.unit FROM samples s
            LEFT JOIN datasets d ON d.dataset_id = s.dataset_id
            WHERE ($sample_ids IS NULL OR s.sample_id IN (SELECT unnest($sample_ids)))
              AND ($dataset_id IS NULL OR s.dataset_id = $dataset_id)
              AND ($group_label IS NULL OR s.group_label = $group_label)
              AND ($organ IS NULL OR s.organ = $organ)
              AND ($genotype IS NULL OR s.genotype = $genotype)
              AND ($is_control IS NULL OR s.is_control = $is_control)
            ORDER BY s.dataset_id, s.organ, s.group_label, s.sample_id
            """,
            {
                "sample_ids": list(sample_ids) if sample_ids else None,
                "dataset_id": dataset_id,
                "group_label": group_label,
                "organ": organ,
                "genotype": genotype,
                "is_control": is_control,
            },
        )

    def default_controls(self, case_samples: pd.DataFrame) -> pd.DataFrame:
        """case と同一 dataset × organ の対照サンプル（既定の WT）を返す。

        比較対象を省略したときの既定挙動。case 側と同じ研究・同じ臓器に
        限定することで、意図しない研究間比較が既定にならないようにする。
        """
        if case_samples.empty:
            return case_samples
        pairs = case_samples[["dataset_id", "organ"]].drop_duplicates()
        frames = []
        for _, row in pairs.iterrows():
            found = self.resolve_samples(
                dataset_id=row["dataset_id"], organ=row["organ"], is_control=True
            )
            frames.append(found)
        if not frames:
            return pd.DataFrame(columns=case_samples.columns)
        controls = pd.concat(frames, ignore_index=True)
        # case に含まれるサンプルは対照から除く（同一群が両側に入る事故を防ぐ）
        return controls[~controls["sample_id"].isin(set(case_samples["sample_id"]))].reset_index(drop=True)


_store: Store | None = None


def get_store() -> Store:
    """プロセス内で 1 つの Store を共有する。"""
    global _store
    if _store is None:
        _store = Store()
    else:
        _store.reload_if_stale()
    return _store


def reset_store() -> None:
    """テストが data/build を差し替えた後に呼ぶ。"""
    global _store
    _store = None
