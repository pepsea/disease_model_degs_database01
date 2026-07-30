"""CSV の列仕様と検証。

設計上の要点は「エラーを 1 件目で止めず、ファイル名・行番号付きで全件
列挙する」こと。キュレーターが CSV を直せば済む状態にするため、致命的な
エラー (error) と、登録は通るが確認してほしい事項 (warning) を分離する。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal

import pandas as pd

from . import config

Level = Literal["error", "warning"]

_TRUE = {"true", "t", "1", "yes", "y"}
_FALSE = {"false", "f", "0", "no", "n"}


@dataclass
class Issue:
    """検証で見つかった 1 件の問題。"""

    level: Level
    file: str
    message: str
    row: int | None = None
    column: str | None = None

    def format(self) -> str:
        where = self.file
        if self.row is not None:
            where += f":{self.row}"
        if self.column:
            where += f" [{self.column}]"
        return f"{self.level.upper():7s} {where}  {self.message}"

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "file": self.file,
            "row": self.row,
            "column": self.column,
            "message": self.message,
        }


class IssueLog:
    """検証結果の蓄積。"""

    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def error(self, file: str, message: str, row: int | None = None, column: str | None = None) -> None:
        self.issues.append(Issue("error", file, message, row, column))

    def warn(self, file: str, message: str, row: int | None = None, column: str | None = None) -> None:
        self.issues.append(Issue("warning", file, message, row, column))

    def extend(self, other: Iterable[Issue]) -> None:
        self.issues.extend(other)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def has_errors(self) -> bool:
        return any(i.level == "error" for i in self.issues)

    def report(self) -> str:
        if not self.issues:
            return "問題は見つかりませんでした。"
        # error を先に、次に file / row 順で並べる
        order = {"error": 0, "warning": 1}
        rows = sorted(self.issues, key=lambda i: (order[i.level], i.file, i.row or 0))
        return "\n".join(i.format() for i in rows)


@dataclass(frozen=True)
class TableSpec:
    """マスタ CSV 1 種類の列契約。"""

    key: str
    filename: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    primary_key: str | None = None
    bool_columns: tuple[str, ...] = ()
    numeric_columns: tuple[str, ...] = ()
    # 処理が値で分岐する列は統制必須 (error)
    enums: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # 表記ゆれを防ぎたいが自由記述も許す列は vocab 照合 (warning)
    vocab: dict[str, str] = field(default_factory=dict)
    file_required: bool = True

    @property
    def columns(self) -> tuple[str, ...]:
        return self.required + self.optional


TABLE_SPECS: dict[str, TableSpec] = {
    "models": TableSpec(
        key="models",
        filename="models.csv",
        required=("model_id", "model_name", "species", "modality", "disease_category"),
        optional=("strain", "target_gene", "description", "reference_url"),
        primary_key="model_id",
        vocab={"species": "species", "modality": "modality"},
    ),
    "datasets": TableSpec(
        key="datasets",
        filename="datasets.csv",
        required=("dataset_id", "title", "model_id", "species", "assay", "unit", "gene_id_type"),
        optional=(
            "platform",
            "duplicate_policy",
            "pmid",
            "geo_url",
            "submitted_by",
            "notes",
        ),
        primary_key="dataset_id",
        enums={
            "unit": config.UNITS,
            "gene_id_type": config.GENE_ID_TYPES,
            "duplicate_policy": config.DUPLICATE_POLICIES,
        },
        vocab={"species": "species"},
    ),
    "samples": TableSpec(
        key="samples",
        filename="samples.csv",
        required=(
            "sample_id",
            "dataset_id",
            "model_id",
            "group_label",
            "genotype",
            "is_control",
            "organ",
        ),
        optional=(
            "tissue_detail",
            "sex",
            "age_weeks",
            "treatment",
            "replicate",
            "batch",
        ),
        primary_key="sample_id",
        bool_columns=("is_control",),
        numeric_columns=("age_weeks",),
        vocab={"organ": "organ"},
    ),
    "genes": TableSpec(
        key="genes",
        filename="genes.csv",
        required=("gene_id",),
        optional=("symbol", "name", "species", "ensembl", "entrez", "biotype", "synonyms"),
        primary_key="gene_id",
        file_required=False,
    ),
    "comparisons": TableSpec(
        key="comparisons",
        filename="comparisons.csv",
        required=("comparison_id", "dataset_id", "case_group_label", "control_group_label"),
        optional=("organ", "method", "label"),
        primary_key="comparison_id",
        file_required=False,
    ),
}

DEG_COLUMNS_REQUIRED = ("gene_id", "log2fc")
DEG_COLUMNS_OPTIONAL = ("pvalue", "padj", "base_mean")


def parse_bool(value: object) -> bool | None:
    """TRUE/FALSE/1/0/yes/no を受理する。解釈できなければ None。"""
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return None


def read_csv(path: Path, log: IssueLog) -> pd.DataFrame | None:
    """CSV を全列 str で読む。型変換は列仕様に従って後段で行う。"""
    try:
        # sep=None + engine="python" で csv/tsv を自動判別する
        df = pd.read_csv(
            path,
            dtype=str,
            keep_default_na=False,
            na_values=[""],
            sep=None,
            engine="python",
            comment=None,
        )
    except pd.errors.EmptyDataError:
        log.error(path.name, "ファイルが空、またはヘッダ行がありません。")
        return None
    except (csv.Error, UnicodeDecodeError, ValueError) as exc:
        log.error(path.name, f"CSV として読み込めません: {exc}")
        return None
    # 前後の空白は ID 比較の事故になるため読み込み時に落とす
    df.columns = [str(c).strip() for c in df.columns]
    for col in df.columns:
        df[col] = df[col].map(lambda v: v.strip() if isinstance(v, str) else v)
    return df


def load_vocab(stem: str) -> tuple[set[str], dict[str, str]]:
    """統制語彙を読み、`(正式term集合, 同義語->term の対応)` を返す。"""
    path = config.vocab_dir() / f"{stem}.csv"
    terms: set[str] = set()
    synonyms: dict[str, str] = {}
    if not path.exists():
        return terms, synonyms
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception:
        return terms, synonyms
    if "term" not in df.columns:
        return terms, synonyms
    for _, row in df.iterrows():
        term = str(row["term"]).strip()
        if not term:
            continue
        terms.add(term)
        synonyms[term.lower()] = term
        raw = str(row.get("synonyms", "") or "")
        for syn in raw.split(";"):
            syn = syn.strip().lower()
            if syn:
                synonyms[syn] = term
    return terms, synonyms


def _row_line(index: int) -> int:
    """pandas の 0 始まり index を、ヘッダを含む CSV の行番号に直す。"""
    return index + 2


def validate_table(spec: TableSpec, df: pd.DataFrame, log: IssueLog) -> pd.DataFrame:
    """1 テーブルを検証し、型変換済みのフレームを返す。"""
    fname = spec.filename

    missing = [c for c in spec.required if c not in df.columns]
    for col in missing:
        log.error(fname, f"必須列 '{col}' がありません。", column=col)
    if missing:
        # 必須列が無い場合は行レベルの検証まで進めない
        return df

    unknown = [c for c in df.columns if c not in spec.columns]
    if unknown:
        # 作業メモ列を残したままでも登録できるようにする（無視するだけ）
        log.warn(fname, f"仕様外の列は無視されます: {', '.join(sorted(unknown))}")

    # 必須列の空欄
    for col in spec.required:
        blank = df.index[df[col].isna() | (df[col].astype(str).str.len() == 0)]
        for idx in blank:
            log.error(fname, f"必須列 '{col}' が空欄です。", row=_row_line(idx), column=col)

    # 主キーの重複
    if spec.primary_key and spec.primary_key in df.columns:
        pk = spec.primary_key
        dup_mask = df[pk].duplicated(keep=False) & df[pk].notna()
        for value, group in df[dup_mask].groupby(pk):
            lines = ", ".join(str(_row_line(i)) for i in group.index)
            log.error(fname, f"{pk} '{value}' が重複しています（行 {lines}）。", column=pk)

    # 統制必須の列
    for col, allowed in spec.enums.items():
        if col not in df.columns:
            continue
        for idx, value in df[col].items():
            if value is None or (isinstance(value, float) and pd.isna(value)) or value == "":
                continue
            if value not in allowed:
                log.error(
                    fname,
                    f"'{col}' の値 '{value}' は不正です。使用可能: {', '.join(allowed)}",
                    row=_row_line(idx),
                    column=col,
                )

    # 語彙照合（警告のみ・同義語なら正式名を提示）
    for col, vocab_stem in spec.vocab.items():
        if col not in df.columns:
            continue
        terms, synonyms = load_vocab(vocab_stem)
        if not terms:
            continue
        for idx, value in df[col].items():
            if not value or pd.isna(value) or value in terms:
                continue
            suggestion = synonyms.get(str(value).lower())
            hint = f" '{suggestion}' の表記ゆれの可能性があります。" if suggestion else ""
            log.warn(
                fname,
                f"'{col}' の値 '{value}' は {vocab_stem} 語彙にありません。{hint}",
                row=_row_line(idx),
                column=col,
            )

    # 真偽値
    for col in spec.bool_columns:
        if col not in df.columns:
            continue
        parsed = df[col].map(parse_bool)
        for idx in df.index[parsed.isna() & df[col].notna()]:
            log.error(
                fname,
                f"'{col}' の値 '{df.at[idx, col]}' を真偽値として解釈できません。TRUE / FALSE を使ってください。",
                row=_row_line(idx),
                column=col,
            )
        df[col] = parsed.fillna(False).astype(bool)

    # 数値
    for col in spec.numeric_columns:
        if col not in df.columns:
            continue
        parsed = pd.to_numeric(df[col], errors="coerce")
        for idx in df.index[parsed.isna() & df[col].notna()]:
            log.error(
                fname,
                f"'{col}' の値 '{df.at[idx, col]}' を数値として解釈できません。",
                row=_row_line(idx),
                column=col,
            )
        df[col] = parsed

    # 仕様上の任意列が無い場合も後段が列名で参照できるように補う
    for col in spec.optional:
        if col not in df.columns:
            df[col] = pd.NA

    return df


def validate_references(tables: dict[str, pd.DataFrame], log: IssueLog) -> None:
    """テーブル間の参照整合性を検証する。"""
    models = tables.get("models")
    datasets = tables.get("datasets")
    samples = tables.get("samples")
    comparisons = tables.get("comparisons")

    model_ids = set(models["model_id"].dropna()) if models is not None and "model_id" in models else set()
    dataset_ids = (
        set(datasets["dataset_id"].dropna()) if datasets is not None and "dataset_id" in datasets else set()
    )

    if datasets is not None and "model_id" in datasets and model_ids:
        for idx, value in datasets["model_id"].items():
            if value and value not in model_ids:
                log.error(
                    "datasets.csv",
                    f"model_id '{value}' が models.csv にありません。",
                    row=_row_line(idx),
                    column="model_id",
                )

    if samples is not None and dataset_ids and "dataset_id" in samples:
        for idx, value in samples["dataset_id"].items():
            if value and value not in dataset_ids:
                log.error(
                    "samples.csv",
                    f"dataset_id '{value}' が datasets.csv にありません。",
                    row=_row_line(idx),
                    column="dataset_id",
                )
    if samples is not None and model_ids and "model_id" in samples:
        for idx, value in samples["model_id"].items():
            if value and value not in model_ids:
                log.error(
                    "samples.csv",
                    f"model_id '{value}' が models.csv にありません。",
                    row=_row_line(idx),
                    column="model_id",
                )

    # 既定比較（WT 自動選択）が成立するかの確認
    if samples is not None and {"dataset_id", "organ", "is_control"} <= set(samples.columns):
        for (dataset_id, organ), group in samples.groupby(["dataset_id", "organ"]):
            if not group["is_control"].any():
                log.warn(
                    "samples.csv",
                    f"dataset_id '{dataset_id}' / organ '{organ}' に is_control=TRUE のサンプルがありません。"
                    " この組み合わせでは比較対象の自動選択（WT 既定）ができません。",
                    column="is_control",
                )

    # 比較定義が実在する群を指しているか
    if comparisons is not None and samples is not None and not comparisons.empty:
        if {"dataset_id", "group_label"} <= set(samples.columns):
            valid_groups = set(zip(samples["dataset_id"], samples["group_label"]))
            for idx, row in comparisons.iterrows():
                dataset_id = row.get("dataset_id")
                if dataset_id and dataset_ids and dataset_id not in dataset_ids:
                    log.error(
                        "comparisons.csv",
                        f"dataset_id '{dataset_id}' が datasets.csv にありません。",
                        row=_row_line(idx),
                        column="dataset_id",
                    )
                    continue
                for col in ("case_group_label", "control_group_label"):
                    label = row.get(col)
                    if label and (dataset_id, label) not in valid_groups:
                        log.error(
                            "comparisons.csv",
                            f"'{col}' の群 '{label}' が dataset '{dataset_id}' の samples.csv に存在しません。",
                            row=_row_line(idx),
                            column=col,
                        )


def find_expression_file(dataset_id: str) -> Path | None:
    """`data/expression/<dataset_id>.*` を拡張子候補から探す。"""
    base = config.expression_dir()
    for suffix in config.EXPRESSION_SUFFIXES:
        candidate = base / f"{dataset_id}{suffix}"
        if candidate.exists():
            return candidate
    return None
