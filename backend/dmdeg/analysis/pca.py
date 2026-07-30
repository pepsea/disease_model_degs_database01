"""主成分分析。

高変動遺伝子の選定は `store.top_variable_genes()` が SQL 側で行うため、
ここに渡ってくるのは既に絞り込まれたマトリクス。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import normalize


def run_pca(
    matrix: pd.DataFrame,
    units: pd.Series | None = None,
    dataset_of: pd.Series | None = None,
    n_components: int = 5,
    scale_within_datasets: bool = False,
) -> dict:
    """サンプル座標・寄与率・ローディングを返す。

    `matrix` は遺伝子 × サンプルの正規化済み線形値。
    `scale_within_datasets=True` でデータセット内 z-score に切り替える
    （研究横断でバッチ差を抑えたい場合）。
    """
    if matrix.empty or matrix.shape[1] < 2:
        return {
            "samples": [],
            "explained_variance_ratio": [],
            "n_genes": int(matrix.shape[0]) if not matrix.empty else 0,
            "components": [],
            "loadings": [],
            "message": "PCA には 2 サンプル以上が必要です。",
        }

    logged = normalize.to_log2_mixed(matrix, units) if units is not None else normalize.to_log2(matrix)

    if scale_within_datasets and dataset_of is not None:
        scaled = normalize.zscore_within_datasets(logged, dataset_of)
    else:
        scaled = normalize.zscore_rows(logged)

    # 分散が 0 の遺伝子は情報を持たないので落とす
    scaled = scaled.loc[scaled.std(axis=1, ddof=0) > 0]
    if scaled.empty:
        return {
            "samples": [],
            "explained_variance_ratio": [],
            "n_genes": 0,
            "components": [],
            "loadings": [],
            "message": "分散のある遺伝子がありません。",
        }

    # 行=サンプル, 列=遺伝子 にしてサンプル平均を除去
    x = scaled.to_numpy(dtype=float).T
    x = x - x.mean(axis=0, keepdims=True)

    n_components = int(max(1, min(n_components, min(x.shape) - 1 if min(x.shape) > 1 else 1)))
    u, s, vt = np.linalg.svd(x, full_matrices=False)

    total = float((s**2).sum())
    ratios = (s**2 / total) if total > 0 else np.zeros_like(s)
    coords = u[:, :n_components] * s[:n_components]

    samples = []
    for i, sample_id in enumerate(scaled.columns):
        entry: dict = {"sample_id": sample_id}
        for c in range(n_components):
            entry[f"PC{c + 1}"] = float(coords[i, c])
        samples.append(entry)

    # 各主成分に寄与の大きい遺伝子（絶対値上位）
    loadings = []
    gene_ids = list(scaled.index)
    for c in range(n_components):
        vector = vt[c]
        top = np.argsort(-np.abs(vector))[:20]
        loadings.append(
            {
                "component": f"PC{c + 1}",
                "genes": [{"gene_id": gene_ids[j], "loading": float(vector[j])} for j in top],
            }
        )

    return {
        "samples": samples,
        "explained_variance_ratio": [float(r) for r in ratios[:n_components]],
        "components": [f"PC{c + 1}" for c in range(n_components)],
        "n_genes": int(scaled.shape[0]),
        "loadings": loadings,
        "scaled_within_datasets": bool(scale_within_datasets and dataset_of is not None),
    }
