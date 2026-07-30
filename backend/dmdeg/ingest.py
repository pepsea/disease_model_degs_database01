"""`data/` の CSV を検証し、`build/` の検索用ストアを再構築する。

    python -m dmdeg.ingest --check   # 検証のみ
    python -m dmdeg.ingest           # 検証 + ビルド

正となるデータは常に `data/` の CSV。`build/` は本コマンドが機械的に
生成する派生物であり、削除しても再実行で完全に復元される。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from . import config, schema
from .schema import IssueLog, TableSpec

EXPRESSION_SCHEMA = pa.schema(
    [
        pa.field("gene_id", pa.string()),
        pa.field("sample_id", pa.string()),
        pa.field("value", pa.float32()),
    ]
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _coerce_text_columns(df: pd.DataFrame, keep_numeric: set[str]) -> pd.DataFrame:
    """文字列列を明示的に string 型にする。

    全行が空欄の任意列をそのまま書くと parquet 上で DOUBLE 型になり、
    閲覧側の `lower(col)` や文字列比較が型エラーで落ちる。
    """
    out = df.copy()
    for column in out.columns:
        if column in keep_numeric:
            continue
        out[column] = out[column].astype("string")
    return out


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 全列を string 化せず、pandas の dtype をそのまま尊重する。
    # 空フレームでも列名を保った parquet を残し、閲覧側のクエリを単純に保つ。
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, path, compression="zstd")


def load_tables(log: IssueLog) -> dict[str, pd.DataFrame]:
    """マスタ CSV を読み、列単位の検証まで済ませたフレーム群を返す。"""
    tables: dict[str, pd.DataFrame] = {}
    for key, spec in schema.TABLE_SPECS.items():
        path = config.data_dir() / spec.filename
        if not path.exists():
            if spec.file_required:
                log.error(spec.filename, "ファイルがありません。")
            tables[key] = _empty_frame(spec)
            continue
        df = schema.read_csv(path, log)
        if df is None:
            tables[key] = _empty_frame(spec)
            continue
        tables[key] = schema.validate_table(spec, df, log)
    schema.validate_references(tables, log)
    return tables


def _empty_frame(spec: TableSpec) -> pd.DataFrame:
    df = pd.DataFrame({col: pd.Series(dtype="object") for col in spec.columns})
    for col in spec.bool_columns:
        df[col] = df[col].astype(bool)
    return df


def _read_matrix(path: Path, log: IssueLog) -> pd.DataFrame | None:
    """発現マトリクス（ワイド形式）を読む。1 列目を gene_id とみなす。"""
    try:
        df = pd.read_csv(path, sep=None, engine="python", dtype={0: str})
    except pd.errors.EmptyDataError:
        log.error(path.name, "発現マトリクスが空です。")
        return None
    except Exception as exc:  # 壊れた区切り・混在型など
        log.error(path.name, f"発現マトリクスを読み込めません: {exc}")
        return None
    if df.shape[1] < 2:
        log.error(path.name, "サンプル列がありません。1 列目 gene_id、2 列目以降をサンプル列にしてください。")
        return None
    first = df.columns[0]
    if first.lower() not in {"gene_id", "gene", "geneid", "symbol", "id", ""}:
        log.warn(path.name, f"1 列目 '{first}' を gene_id として扱います。")
    df = df.rename(columns={first: "gene_id"})
    df["gene_id"] = df["gene_id"].astype(str).str.strip()
    return df


def _aggregate_duplicates(df: pd.DataFrame, policy: str, fname: str, log: IssueLog) -> pd.DataFrame:
    """重複 gene_id を duplicate_policy に従って集約する。"""
    dup_count = int(df["gene_id"].duplicated().sum())
    if dup_count == 0:
        return df.set_index("gene_id")
    log.warn(fname, f"重複した gene_id が {dup_count} 件あります。duplicate_policy='{policy}' で集約します。")
    grouped = df.groupby("gene_id", sort=False)
    if policy == "sum":
        return grouped.sum(numeric_only=True)
    if policy == "mean":
        return grouped.mean(numeric_only=True)
    if policy == "first":
        return grouped.first()
    return grouped.max(numeric_only=True)


def process_expression(
    tables: dict[str, pd.DataFrame], log: IssueLog, write: bool
) -> tuple[pd.DataFrame, dict[str, dict]]:
    """各データセットの発現マトリクスを検証し、ロング形式 parquet を書く。

    戻り値は (サンプル単位の集計統計, データセット単位の統計)。
    """
    datasets = tables["datasets"]
    samples = tables["samples"]
    sample_stats: list[pd.DataFrame] = []
    dataset_stats: dict[str, dict] = {}

    if write:
        target = config.expression_parquet_dir()
        if target.exists():
            shutil.rmtree(target)

    if datasets.empty or "dataset_id" not in datasets.columns:
        return pd.DataFrame(columns=["sample_id", "library_size", "detected_genes"]), dataset_stats

    for _, dataset in datasets.iterrows():
        dataset_id = dataset.get("dataset_id")
        if not dataset_id or pd.isna(dataset_id):
            continue
        path = schema.find_expression_file(dataset_id)
        if path is None:
            log.error(
                "datasets.csv",
                f"dataset '{dataset_id}' の発現マトリクスが見つかりません。"
                f" data/expression/{dataset_id}.csv を配置してください。",
                column="dataset_id",
            )
            continue

        matrix = _read_matrix(path, log)
        if matrix is None:
            continue

        declared = samples.loc[samples["dataset_id"] == dataset_id, "sample_id"] if not samples.empty else pd.Series(dtype=str)
        declared_set = set(declared.dropna())
        matrix_samples = [c for c in matrix.columns if c != "gene_id"]

        extra = [c for c in matrix_samples if c not in declared_set]
        for col in extra:
            log.error(
                path.name,
                f"サンプル列 '{col}' が samples.csv に登録されていません。",
                column=col,
            )
        missing = sorted(declared_set - set(matrix_samples))
        if missing:
            log.warn(
                path.name,
                f"samples.csv に登録済みだが発現マトリクスに列が無いサンプル: {', '.join(missing)}",
            )

        usable = [c for c in matrix_samples if c in declared_set]
        if not usable:
            log.error(path.name, "samples.csv と対応するサンプル列が 1 つもありません。")
            continue

        values = matrix[["gene_id"] + usable].copy()
        for col in usable:
            values[col] = pd.to_numeric(values[col], errors="coerce")

        nan_ratio = float(values[usable].isna().to_numpy().mean()) if usable else 0.0
        if nan_ratio > 0:
            level = log.error if nan_ratio > 0.5 else log.warn
            level(
                path.name,
                f"数値として解釈できない値が {nan_ratio:.1%} あります。",
            )

        unit = dataset.get("unit")
        negatives = int((values[usable] < 0).to_numpy().sum())
        if negatives and unit in {"counts", "tpm", "fpkm"}:
            log.error(
                path.name,
                f"unit='{unit}' に対して負の値が {negatives} 件あります。単位の申告を確認してください。",
            )

        policy = dataset.get("duplicate_policy")
        if not policy or pd.isna(policy):
            policy = "max"
        wide = _aggregate_duplicates(values, str(policy), path.name, log)

        # counts と申告された値が整数でない場合は二重正規化の疑いを出す
        if unit == "counts":
            finite = wide.to_numpy(dtype="float64", na_value=0.0)
            if finite.size and not (finite == finite.round()).all():
                log.warn(
                    path.name,
                    "unit='counts' ですが非整数の値が含まれます。既に正規化済みの値ではないか確認してください。",
                )

        long = (
            wide.reset_index()
            .melt(id_vars="gene_id", var_name="sample_id", value_name="value")
            .dropna(subset=["value"])
        )
        # gene_id 順に並べると parquet の行グループ統計が効き、
        # 遺伝子 1 件の横断検索でデータセット内の大半をスキップできる
        long = long.sort_values(["gene_id", "sample_id"], kind="stable", ignore_index=True)
        long["value"] = long["value"].astype("float32")

        if write:
            out = config.expression_parquet_dir() / f"dataset_id={dataset_id}" / "part.parquet"
            out.parent.mkdir(parents=True, exist_ok=True)
            table = pa.Table.from_pandas(long[["gene_id", "sample_id", "value"]], schema=EXPRESSION_SCHEMA, preserve_index=False)
            pq.write_table(table, out, compression="zstd")

        stats = (
            long.groupby("sample_id")["value"]
            .agg(library_size="sum", detected_genes=lambda s: int((s > 0).sum()))
            .reset_index()
        )
        sample_stats.append(stats)
        dataset_stats[dataset_id] = {
            "n_genes": int(wide.shape[0]),
            "n_samples": len(usable),
            "source_file": path.name,
            "source_sha256": _sha256(path),
        }

    if sample_stats:
        combined = pd.concat(sample_stats, ignore_index=True)
    else:
        combined = pd.DataFrame(columns=["sample_id", "library_size", "detected_genes"])
    return combined, dataset_stats


def process_degs(tables: dict[str, pd.DataFrame], log: IssueLog) -> pd.DataFrame:
    """外部解析済み DEG 表を読み、1 枚のフレームに束ねる。"""
    comparisons = tables["comparisons"]
    frames: list[pd.DataFrame] = []
    columns = ["comparison_id", *schema.DEG_COLUMNS_REQUIRED[1:], *schema.DEG_COLUMNS_OPTIONAL]
    if comparisons.empty or "comparison_id" not in comparisons.columns:
        return pd.DataFrame(columns=["comparison_id", "gene_id", "log2fc", "pvalue", "padj", "base_mean"])

    for comparison_id in comparisons["comparison_id"].dropna():
        path = config.degs_dir() / f"{comparison_id}.csv"
        if not path.exists():
            # DEG 表は任意。無ければオンザフライ統計のみを提供する。
            continue
        df = schema.read_csv(path, log)
        if df is None:
            continue
        missing = [c for c in schema.DEG_COLUMNS_REQUIRED if c not in df.columns]
        if missing:
            log.error(path.name, f"必須列がありません: {', '.join(missing)}")
            continue
        keep = pd.DataFrame({"comparison_id": comparison_id, "gene_id": df["gene_id"]})
        for col in ("log2fc", "pvalue", "padj", "base_mean"):
            keep[col] = pd.to_numeric(df[col], errors="coerce") if col in df.columns else pd.NA
        frames.append(keep)

    if not frames:
        return pd.DataFrame(columns=["comparison_id", "gene_id", "log2fc", "pvalue", "padj", "base_mean"])
    out = pd.concat(frames, ignore_index=True)
    for col in ("log2fc", "pvalue", "padj", "base_mean"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def build_gene_table(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """発現マトリクスに現れた gene_id を genes.csv の注釈で補完する。"""
    observed: set[str] = set()
    expression_root = config.expression_parquet_dir()
    if expression_root.exists():
        for part in sorted(expression_root.glob("*/part.parquet")):
            ids = pq.read_table(part, columns=["gene_id"])["gene_id"].to_pylist()
            observed.update(ids)

    annotations = tables["genes"]
    # dtype を明示する。空リストから DataFrame を作ると float64 になり、
    # データ未登録の状態（テンプレートのみ）で .str アクセサが落ちる。
    genes = pd.DataFrame({"gene_id": pd.Series(sorted(observed), dtype="string")})
    if not annotations.empty and "gene_id" in annotations.columns:
        annotations = annotations.drop_duplicates(subset="gene_id")
        genes = genes.merge(annotations, on="gene_id", how="outer")
    for col in ("symbol", "name", "species", "ensembl", "entrez", "biotype", "synonyms"):
        if col not in genes.columns:
            genes[col] = pd.NA
        genes[col] = genes[col].astype("string")
    genes["gene_id"] = genes["gene_id"].astype("string")
    # symbol 未指定なら gene_id をそのまま表示名に使う
    genes["symbol"] = genes["symbol"].fillna(genes["gene_id"])
    genes["search_key"] = genes["gene_id"].str.lower()
    genes["symbol_key"] = genes["symbol"].str.lower()
    return genes.sort_values("gene_id", ignore_index=True)


def write_duckdb(log: IssueLog) -> None:
    """ad-hoc SQL 用に parquet への VIEW を張った DuckDB ファイルを作る。

    閲覧アプリはこのファイルに依存せず、`store.py` が同じ VIEW を
    その場で作る。ここで作るのは調査用の利便性のため。
    """
    path = config.duckdb_path()
    if path.exists():
        path.unlink()
    con = duckdb.connect(str(path))
    try:
        from .store import create_views

        create_views(con)
    finally:
        con.close()


def ingest(write: bool = True) -> tuple[IssueLog, dict]:
    """検証と（write=True なら）ビルドを実行し、ログと manifest を返す。"""
    log = IssueLog()
    tables = load_tables(log)

    if write:
        config.parquet_dir().mkdir(parents=True, exist_ok=True)

    sample_stats, dataset_stats = process_expression(tables, log, write=write)
    degs = process_degs(tables, log)

    manifest: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_dir": str(config.data_dir()),
        "counts": {
            "models": int(len(tables["models"])),
            "datasets": int(len(tables["datasets"])),
            "samples": int(len(tables["samples"])),
            "comparisons": int(len(tables["comparisons"])),
            "deg_rows": int(len(degs)),
        },
        "datasets": dataset_stats,
        "issues": [i.to_dict() for i in log.issues],
    }

    if not write:
        return log, manifest

    if log.has_errors:
        # エラーがある状態で中途半端なストアを残さない
        return log, manifest

    samples = tables["samples"].copy()
    if not sample_stats.empty and not samples.empty:
        samples = samples.merge(sample_stats, on="sample_id", how="left")
    else:
        samples["library_size"] = pd.NA
        samples["detected_genes"] = pd.NA

    _write_parquet(
        _coerce_text_columns(tables["models"], set()), config.parquet_dir() / "models.parquet"
    )
    _write_parquet(
        _coerce_text_columns(tables["datasets"], set()), config.parquet_dir() / "datasets.parquet"
    )
    _write_parquet(
        _coerce_text_columns(samples, {"is_control", "age_weeks", "library_size", "detected_genes"}),
        config.parquet_dir() / "samples.parquet",
    )
    _write_parquet(
        _coerce_text_columns(tables["comparisons"], set()),
        config.parquet_dir() / "comparisons.parquet",
    )
    _write_parquet(
        _coerce_text_columns(degs, {"log2fc", "pvalue", "padj", "base_mean"}),
        config.parquet_dir() / "degs.parquet",
    )
    _write_parquet(
        _coerce_text_columns(build_gene_table(tables), set()),
        config.parquet_dir() / "genes.parquet",
    )

    write_duckdb(log)

    manifest["counts"]["genes"] = int(len(pq.read_table(config.parquet_dir() / "genes.parquet")))
    config.manifest_path().parent.mkdir(parents=True, exist_ok=True)
    config.manifest_path().write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return log, manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="data/ の CSV を検証して build/ を再構築する")
    parser.add_argument("--check", action="store_true", help="検証のみ行い、ビルドしない")
    args = parser.parse_args(argv)

    log, manifest = ingest(write=not args.check)

    print(log.report())
    print()
    n_err, n_warn = len(log.errors), len(log.warnings)
    print(f"エラー {n_err} 件 / 警告 {n_warn} 件")

    if n_err:
        print("エラーがあるためビルドしませんでした。上記を修正して再実行してください。", file=sys.stderr)
        return 1

    counts = manifest["counts"]
    summary = " / ".join(f"{k}={v}" for k, v in counts.items())
    if args.check:
        print(f"検証のみ完了（ビルドなし）: {summary}")
    else:
        print(f"ビルド完了: {summary}")
        print(f"出力先: {config.build_dir()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
