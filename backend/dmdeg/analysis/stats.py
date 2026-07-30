"""2 群比較の統計量。

UI 上は「探索用」として提示するもの。DESeq2 / limma のような分散の
事前分布モデルは持たないため、確定的な結論は `data/degs/` に登録した
外部解析結果を正とする（設計書 §4.3）。

log2FC は正規化済みの線形値の群平均比、検定は log 変換後の値に対して
行う。カウントデータの分布は右に長く裾を引くため、平均の比で効果量を
示しつつ、検定は対称性が改善する log 空間で行うのが妥当。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from ..config import PSEUDOCOUNT

METHODS = ("welch", "mannwhitney")


def benjamini_hochberg(pvalues: np.ndarray) -> np.ndarray:
    """BH 法で FDR 補正した q 値を返す。NaN は NaN のまま保つ。"""
    p = np.asarray(pvalues, dtype=float)
    out = np.full(p.shape, np.nan)
    finite = np.isfinite(p)
    values = p[finite]
    n = values.size
    if n == 0:
        return out
    order = np.argsort(values, kind="stable")
    ranked = values[order]
    adjusted = ranked * n / np.arange(1, n + 1)
    # 単調性を担保するため後ろから累積最小を取る
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    adjusted = np.clip(adjusted, 0.0, 1.0)
    restored = np.empty(n, dtype=float)
    restored[order] = adjusted
    out[finite] = restored
    return out


def cohens_d(case: np.ndarray, control: np.ndarray) -> np.ndarray:
    """プールした標準偏差による効果量（log 空間で計算する）。"""
    n1 = case.shape[1]
    n2 = control.shape[1]
    if n1 < 2 or n2 < 2:
        return np.full(case.shape[0], np.nan)
    v1 = np.nanvar(case, axis=1, ddof=1)
    v2 = np.nanvar(control, axis=1, ddof=1)
    pooled = np.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2))
    with np.errstate(invalid="ignore", divide="ignore"):
        d = (np.nanmean(case, axis=1) - np.nanmean(control, axis=1)) / pooled
    return np.where(np.isfinite(d), d, np.nan)


def compare_groups(
    case_matrix: pd.DataFrame,
    control_matrix: pd.DataFrame,
    method: str = "welch",
) -> pd.DataFrame:
    """遺伝子ごとの log2FC と検定結果を返す。

    入力はどちらも「遺伝子 × サンプル」の正規化済み線形値で、行 index
    (gene_id) が揃っていること。
    """
    if method not in METHODS:
        raise ValueError(f"未対応の method です: {method}. 使用可能: {', '.join(METHODS)}")

    genes = case_matrix.index
    if not control_matrix.index.equals(genes):
        # 共通遺伝子に揃える（プラットフォーム差でずれることがある）
        genes = case_matrix.index.intersection(control_matrix.index)
        case_matrix = case_matrix.loc[genes]
        control_matrix = control_matrix.loc[genes]

    case = case_matrix.to_numpy(dtype=float)
    control = control_matrix.to_numpy(dtype=float)

    mean_case = np.nanmean(case, axis=1) if case.size else np.array([])
    mean_control = np.nanmean(control, axis=1) if control.size else np.array([])

    with np.errstate(divide="ignore", invalid="ignore"):
        log2fc = np.log2((mean_case + PSEUDOCOUNT) / (mean_control + PSEUDOCOUNT))

    log_case = np.log2(np.clip(case, 0, None) + PSEUDOCOUNT)
    log_control = np.log2(np.clip(control, 0, None) + PSEUDOCOUNT)

    n1, n2 = case.shape[1], control.shape[1]
    if n1 < 2 or n2 < 2:
        # 反復が足りない場合は検定せず、効果量のみ返す
        pvalue = np.full(len(genes), np.nan)
    elif method == "welch":
        with np.errstate(invalid="ignore"):
            result = stats.ttest_ind(log_case, log_control, axis=1, equal_var=False, nan_policy="omit")
        pvalue = np.asarray(result.pvalue, dtype=float)
    else:
        pvalue = np.full(len(genes), np.nan)
        for i in range(len(genes)):
            a = log_case[i][np.isfinite(log_case[i])]
            b = log_control[i][np.isfinite(log_control[i])]
            if a.size < 1 or b.size < 1 or (np.all(a == a[0]) and np.all(b == b[0]) and a[0] == b[0]):
                continue
            pvalue[i] = stats.mannwhitneyu(a, b, alternative="two-sided").pvalue

    frame = pd.DataFrame(
        {
            "gene_id": list(genes),
            "log2fc": log2fc,
            "mean_case": mean_case,
            "mean_control": mean_control,
            "base_mean": (mean_case * n1 + mean_control * n2) / max(n1 + n2, 1),
            "pvalue": pvalue,
            "padj": benjamini_hochberg(pvalue),
            "effect_size": cohens_d(log_case, log_control),
            "n_case": n1,
            "n_control": n2,
        }
    )
    return frame.sort_values(
        ["padj", "pvalue", "log2fc"], ascending=[True, True, False], na_position="last", ignore_index=True
    )


def summarize(frame: pd.DataFrame, log2fc_threshold: float = 1.0, padj_threshold: float = 0.05) -> dict:
    """volcano の閾値表示に添えるサマリ。"""
    if frame.empty:
        return {"n_genes": 0, "n_up": 0, "n_down": 0, "n_tested": 0}
    padj = frame["padj"]
    significant = padj.notna() & (padj <= padj_threshold)
    up = significant & (frame["log2fc"] >= log2fc_threshold)
    down = significant & (frame["log2fc"] <= -log2fc_threshold)
    return {
        "n_genes": int(len(frame)),
        "n_tested": int(frame["pvalue"].notna().sum()),
        "n_up": int(up.sum()),
        "n_down": int(down.sum()),
        "log2fc_threshold": log2fc_threshold,
        "padj_threshold": padj_threshold,
    }
