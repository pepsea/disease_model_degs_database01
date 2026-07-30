"""サンプル間相関と階層クラスタリング。

ヒートマップの行・列順序をここで決める。UI 側は返された順序で描くだけ。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster import hierarchy
from scipy.spatial.distance import squareform

from . import normalize

CORRELATION_METHODS = ("pearson", "spearman")


def _leaf_order(matrix: np.ndarray, labels: list[str]) -> list[str]:
    """相関距離による ward 法で並べ替え順を求める。"""
    if len(labels) < 3:
        return labels
    corr = np.corrcoef(matrix)
    corr = np.nan_to_num(corr, nan=0.0)
    distance = 1.0 - corr
    np.fill_diagonal(distance, 0.0)
    # 数値誤差で対称性が崩れることがあるため明示的に対称化する
    distance = (distance + distance.T) / 2
    distance[distance < 0] = 0.0
    linkage = hierarchy.linkage(squareform(distance, checks=False), method="average")
    order = hierarchy.leaves_list(linkage)
    return [labels[i] for i in order]


def correlation(
    matrix: pd.DataFrame,
    units: pd.Series | None = None,
    method: str = "spearman",
) -> dict:
    """サンプル間相関行列とクラスタ順序を返す。"""
    if method not in CORRELATION_METHODS:
        raise ValueError(f"未対応の method です: {method}. 使用可能: {', '.join(CORRELATION_METHODS)}")
    if matrix.empty or matrix.shape[1] < 2:
        return {"samples": [], "matrix": [], "method": method, "message": "2 サンプル以上必要です。"}

    logged = normalize.to_log2_mixed(matrix, units) if units is not None else normalize.to_log2(matrix)
    corr = logged.corr(method=method)
    labels = list(corr.columns)
    order = _leaf_order(corr.to_numpy(dtype=float), labels)
    corr = corr.loc[order, order]
    return {
        "samples": order,
        "matrix": [[None if pd.isna(v) else float(v) for v in row] for row in corr.to_numpy()],
        "method": method,
    }


def heatmap(
    matrix: pd.DataFrame,
    units: pd.Series | None = None,
    dataset_of: pd.Series | None = None,
    scale_within_datasets: bool = False,
    cluster_genes: bool = True,
    cluster_samples: bool = True,
) -> dict:
    """遺伝子 × サンプルのヒートマップ行列を、並べ替え済みで返す。"""
    if matrix.empty:
        return {"genes": [], "samples": [], "values": [], "message": "対象データがありません。"}

    logged = normalize.to_log2_mixed(matrix, units) if units is not None else normalize.to_log2(matrix)
    if scale_within_datasets and dataset_of is not None:
        scaled = normalize.zscore_within_datasets(logged, dataset_of)
    else:
        scaled = normalize.zscore_rows(logged)

    scaled = scaled.loc[scaled.std(axis=1, ddof=0) > 0]
    if scaled.empty:
        return {"genes": [], "samples": [], "values": [], "message": "分散のある遺伝子がありません。"}

    gene_order = list(scaled.index)
    sample_order = list(scaled.columns)
    if cluster_genes and len(gene_order) >= 3:
        gene_order = _leaf_order(scaled.to_numpy(dtype=float), gene_order)
    if cluster_samples and len(sample_order) >= 3:
        sample_order = _leaf_order(scaled.to_numpy(dtype=float).T, sample_order)

    ordered = scaled.loc[gene_order, sample_order]
    return {
        "genes": gene_order,
        "samples": sample_order,
        "values": [[None if pd.isna(v) else float(v) for v in row] for row in ordered.to_numpy()],
        "scaled_within_datasets": bool(scale_within_datasets and dataset_of is not None),
    }
