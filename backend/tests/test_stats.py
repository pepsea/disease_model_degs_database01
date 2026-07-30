"""比較統計の検証。scipy の直接計算と一致することを確かめる。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats as sp

from dmdeg.analysis.stats import benjamini_hochberg, compare_groups, summarize


def test_benjamini_hochberg_matches_reference():
    """既知の p 値列に対する BH 補正値。"""
    p = np.array([0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216])
    q = benjamini_hochberg(p)
    # 手計算: p_i * n / i を後ろから累積最小
    n = len(p)
    expected = np.minimum.accumulate((p * n / np.arange(1, n + 1))[::-1])[::-1]
    assert np.allclose(q, np.clip(expected, 0, 1))
    # 単調非減少であること
    assert np.all(np.diff(q) >= -1e-12)
    # 補正後は元の p 以上
    assert np.all(q >= p - 1e-12)


def test_benjamini_hochberg_preserves_nan():
    q = benjamini_hochberg(np.array([0.01, np.nan, 0.5]))
    assert np.isnan(q[1])
    assert not np.isnan(q[0]) and not np.isnan(q[2])


def test_benjamini_hochberg_empty():
    assert benjamini_hochberg(np.array([])).size == 0
    assert np.isnan(benjamini_hochberg(np.array([np.nan]))).all()


def test_welch_pvalue_matches_scipy():
    """compare_groups の p 値が scipy の Welch 検定と一致する。

    実装は log2(x+1) 変換後の値に検定をかけるので、参照側も同じ変換をする。
    """
    rng = np.random.default_rng(7)
    genes = [f"G{i}" for i in range(40)]
    case = pd.DataFrame(rng.lognormal(3, 1, size=(40, 5)), index=genes)
    control = pd.DataFrame(rng.lognormal(3, 1, size=(40, 4)), index=genes)

    result = compare_groups(case, control, method="welch").set_index("gene_id").loc[genes]

    reference = sp.ttest_ind(
        np.log2(case.to_numpy() + 1.0),
        np.log2(control.to_numpy() + 1.0),
        axis=1,
        equal_var=False,
    ).pvalue
    assert np.allclose(result["pvalue"].to_numpy(), reference, rtol=1e-10, atol=1e-12)


def test_log2fc_is_ratio_of_normalized_means():
    """log2FC は線形値の群平均比（+1 の擬似カウント付き）。"""
    case = pd.DataFrame({"s1": [100.0], "s2": [100.0]}, index=["G1"])
    control = pd.DataFrame({"c1": [10.0], "c2": [10.0]}, index=["G1"])
    result = compare_groups(case, control)
    assert result.loc[0, "log2fc"] == pytest.approx(np.log2(101.0 / 11.0))
    assert result.loc[0, "mean_case"] == pytest.approx(100.0)
    assert result.loc[0, "mean_control"] == pytest.approx(10.0)


def test_direction_of_change():
    """上昇は正、下降は負になる。"""
    case = pd.DataFrame({"s1": [200.0, 5.0], "s2": [210.0, 6.0]}, index=["up", "down"])
    control = pd.DataFrame({"c1": [20.0, 90.0], "c2": [22.0, 100.0]}, index=["up", "down"])
    result = compare_groups(case, control).set_index("gene_id")
    assert result.loc["up", "log2fc"] > 0
    assert result.loc["down", "log2fc"] < 0


def test_insufficient_replicates_skips_test_but_keeps_log2fc():
    """反復が 1 の群では検定せず log2FC のみ返す。"""
    case = pd.DataFrame({"s1": [100.0]}, index=["G1"])
    control = pd.DataFrame({"c1": [10.0]}, index=["G1"])
    result = compare_groups(case, control)
    assert np.isnan(result.loc[0, "pvalue"])
    assert np.isnan(result.loc[0, "padj"])
    assert result.loc[0, "log2fc"] > 0


def test_mismatched_gene_sets_are_intersected():
    case = pd.DataFrame({"s1": [1.0, 2.0], "s2": [1.0, 2.0]}, index=["A", "B"])
    control = pd.DataFrame({"c1": [1.0, 3.0], "c2": [1.0, 3.0]}, index=["B", "C"])
    result = compare_groups(case, control)
    assert result["gene_id"].tolist() == ["B"]


def test_mannwhitney_method_runs():
    rng = np.random.default_rng(11)
    case = pd.DataFrame(rng.lognormal(4, 0.3, size=(10, 5)))
    control = pd.DataFrame(rng.lognormal(2, 0.3, size=(10, 5)))
    result = compare_groups(case, control, method="mannwhitney")
    assert result["pvalue"].notna().all()
    assert (result["log2fc"] > 0).all()


def test_unknown_method_rejected():
    frame = pd.DataFrame({"s1": [1.0], "s2": [1.0]})
    with pytest.raises(ValueError, match="未対応の method"):
        compare_groups(frame, frame, method="deseq2")


def test_summarize_counts_thresholds():
    frame = pd.DataFrame(
        {
            "log2fc": [2.0, -2.0, 0.5, 3.0],
            "padj": [0.01, 0.01, 0.01, 0.9],
            "pvalue": [0.001, 0.001, 0.001, 0.5],
        }
    )
    result = summarize(frame, log2fc_threshold=1.0, padj_threshold=0.05)
    # 上昇 1 件(2.0)・下降 1 件(-2.0)。0.5 は閾値未満、3.0 は padj 不合格
    assert result["n_up"] == 1
    assert result["n_down"] == 1
    assert result["n_genes"] == 4
