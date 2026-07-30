"""発現値の正規化と表示用変換。

CPM 換算は `store.py` の SQL 側で済んでいる。ここでは取得後のマトリクスに
かける変換（log 化、データセット内 z-score）を扱う。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import PSEUDOCOUNT

# log2_intensity は既に log 空間にあるため、二重に log を取らない
ALREADY_LOG_UNITS = {"log2_intensity"}


def to_log2(matrix: pd.DataFrame, unit: str | None = None) -> pd.DataFrame:
    """log2(x + 1) に変換する。既に log 空間の単位はそのまま返す。"""
    if unit in ALREADY_LOG_UNITS:
        return matrix
    return np.log2(matrix.clip(lower=0) + PSEUDOCOUNT)


def to_log2_mixed(matrix: pd.DataFrame, units: pd.Series) -> pd.DataFrame:
    """サンプルごとに単位が違う場合に、列ごとに log 変換を切り替える。

    データセット横断のマトリクスでは microarray (log2_intensity) と
    RNA-seq (counts) が混ざりうるため、列単位で判定する。
    """
    out = matrix.copy()
    for column in out.columns:
        unit = units.get(column)
        if unit in ALREADY_LOG_UNITS:
            continue
        out[column] = np.log2(out[column].clip(lower=0) + PSEUDOCOUNT)
    return out


def zscore_rows(matrix: pd.DataFrame) -> pd.DataFrame:
    """遺伝子ごと（行ごと）に z-score 化する。ヒートマップ表示に使う。"""
    mean = matrix.mean(axis=1)
    std = matrix.std(axis=1, ddof=0).replace(0, np.nan)
    scaled = matrix.sub(mean, axis=0).div(std, axis=0)
    return scaled.fillna(0.0)


def zscore_within_datasets(matrix: pd.DataFrame, dataset_of: pd.Series) -> pd.DataFrame:
    """データセットごとに独立に遺伝子単位 z-score 化する。

    研究間の絶対発現量には技術的交絡が乗るため、横断表示ではデータセット内
    の相対位置に揃える。これが横断比較時の既定。
    """
    out = matrix.copy().astype(float)
    groups: dict[str, list[str]] = {}
    for sample_id in matrix.columns:
        groups.setdefault(str(dataset_of.get(sample_id, "")), []).append(sample_id)
    for columns in groups.values():
        block = matrix[columns]
        mean = block.mean(axis=1)
        std = block.std(axis=1, ddof=0).replace(0, np.nan)
        out[columns] = block.sub(mean, axis=0).div(std, axis=0).fillna(0.0)
    return out


def drop_low_expression(matrix: pd.DataFrame, min_value: float = 0.0, min_samples: int = 1) -> pd.DataFrame:
    """ほぼ全サンプルで検出されない遺伝子を落とす。"""
    keep = (matrix > min_value).sum(axis=1) >= min_samples
    return matrix.loc[keep]
