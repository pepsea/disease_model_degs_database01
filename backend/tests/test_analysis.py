"""PCA・正規化・クラスタリングの検証。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from dmdeg.analysis import cluster, normalize
from dmdeg.analysis.pca import run_pca


def _matrix(rng, n_genes=60, n_samples=8, offset=0.0, split=None):
    values = rng.lognormal(4, 0.4, size=(n_genes, n_samples))
    frame = pd.DataFrame(
        values,
        index=[f"G{i}" for i in range(n_genes)],
        columns=[f"S{i}" for i in range(n_samples)],
    )
    if split is not None:
        # 後半サンプルの一部の遺伝子を持ち上げ、2 群構造を作る
        frame.iloc[:20, split:] *= 2 ** offset
    return frame


def test_explained_variance_is_sorted_and_bounded():
    rng = np.random.default_rng(3)
    result = run_pca(_matrix(rng), n_components=4)
    ratios = result["explained_variance_ratio"]
    assert len(ratios) == 4
    assert all(0.0 <= r <= 1.0 for r in ratios)
    assert ratios == sorted(ratios, reverse=True)
    assert sum(ratios) <= 1.0 + 1e-9


def test_pca_separates_known_two_group_structure():
    """明確な 2 群構造があれば PC1 で符号が分かれる。"""
    rng = np.random.default_rng(5)
    matrix = _matrix(rng, n_samples=10, offset=4.0, split=5)
    result = run_pca(matrix, n_components=2)
    pc1 = {row["sample_id"]: row["PC1"] for row in result["samples"]}
    group_a = [pc1[f"S{i}"] for i in range(5)]
    group_b = [pc1[f"S{i}"] for i in range(5, 10)]
    assert max(group_a) < min(group_b) or max(group_b) < min(group_a)


def test_pca_requires_two_samples():
    frame = pd.DataFrame({"S0": [1.0, 2.0]}, index=["A", "B"])
    result = run_pca(frame)
    assert result["samples"] == []
    assert "2 サンプル以上" in result["message"]


def test_pca_reports_loadings_per_component():
    rng = np.random.default_rng(9)
    result = run_pca(_matrix(rng), n_components=3)
    assert [entry["component"] for entry in result["loadings"]] == ["PC1", "PC2", "PC3"]
    assert all(entry["genes"] for entry in result["loadings"])


def test_log2_skips_already_logged_units():
    frame = pd.DataFrame({"S0": [8.0]}, index=["A"])
    assert normalize.to_log2(frame, unit="log2_intensity").loc["A", "S0"] == 8.0
    assert normalize.to_log2(frame, unit="counts").loc["A", "S0"] == np.log2(9.0)


def test_to_log2_mixed_switches_per_column():
    """列ごとに単位が違う横断マトリクスで、log 変換が列単位に切り替わる。"""
    frame = pd.DataFrame({"rna": [7.0], "array": [7.0]}, index=["A"])
    units = pd.Series({"rna": "counts", "array": "log2_intensity"})
    out = normalize.to_log2_mixed(frame, units)
    assert out.loc["A", "rna"] == np.log2(8.0)
    assert out.loc["A", "array"] == 7.0


def test_zscore_rows_centers_each_gene():
    frame = pd.DataFrame({"a": [1.0, 10.0], "b": [3.0, 30.0]}, index=["G1", "G2"])
    scaled = normalize.zscore_rows(frame)
    assert np.allclose(scaled.mean(axis=1), 0.0)
    # 定数行は 0 に落ちる（NaN を返さない）
    constant = pd.DataFrame({"a": [5.0], "b": [5.0]}, index=["C"])
    assert normalize.zscore_rows(constant).loc["C"].tolist() == [0.0, 0.0]


def test_zscore_within_datasets_is_independent_per_dataset():
    """データセットごとに独立に中心化される。"""
    frame = pd.DataFrame(
        {"a1": [1.0], "a2": [3.0], "b1": [100.0], "b2": [300.0]}, index=["G"]
    )
    dataset_of = pd.Series({"a1": "A", "a2": "A", "b1": "B", "b2": "B"})
    scaled = normalize.zscore_within_datasets(frame, dataset_of)
    assert np.allclose(scaled[["a1", "a2"]].mean(axis=1), 0.0)
    assert np.allclose(scaled[["b1", "b2"]].mean(axis=1), 0.0)
    # 絶対値の大きさに関わらず、両データセットが同じスケールに乗る
    assert scaled.loc["G", "a1"] == scaled.loc["G", "b1"]


def test_correlation_returns_square_ordered_matrix():
    rng = np.random.default_rng(13)
    result = cluster.correlation(_matrix(rng, n_samples=6))
    assert len(result["samples"]) == 6
    assert len(result["matrix"]) == 6
    assert all(len(row) == 6 for row in result["matrix"])
    # 対角は自己相関 1
    for i in range(6):
        assert result["matrix"][i][i] == pytest.approx(1.0)


def test_heatmap_returns_matching_dimensions():
    rng = np.random.default_rng(17)
    result = cluster.heatmap(_matrix(rng, n_genes=25, n_samples=6))
    assert len(result["genes"]) == len(result["values"])
    assert all(len(row) == len(result["samples"]) for row in result["values"])
