"""ルータから使う処理本体。

サンプル選択の解決と、警告（バッチ交絡・反復不足）の判定をここに集約する。
export ルータも同じ関数を通すので、画面表示とダウンロードで結果がずれない。
"""

from __future__ import annotations

import pandas as pd
from fastapi import HTTPException

from ..analysis import cluster, pca, stats
from ..store import Store
from .schemas import (
    CompareRequest,
    CorrelationRequest,
    HeatmapRequest,
    PcaRequest,
    SampleSelection,
)


def resolve_selection(
    store: Store, selection: SampleSelection, allow_all: bool = False
) -> pd.DataFrame:
    """選択条件をサンプル行に解決する。

    条件が空のときの扱いを呼び出し側に選ばせる。PCA など単一集合の解析では
    「全サンプル」が妥当な既定だが、比較の case 側で空を全件と解釈すると
    意図しない比較が黙って走ってしまうため。
    """
    if selection.is_empty():
        if not allow_all:
            return pd.DataFrame()
        return store.resolve_samples()
    return store.resolve_samples(
        sample_ids=selection.sample_ids,
        dataset_id=selection.dataset_id,
        group_label=selection.group_label,
        organ=selection.organ,
        genotype=selection.genotype,
    )


def _batch_warnings(case: pd.DataFrame, control: pd.DataFrame) -> list[str]:
    """研究間比較・反復不足の注意喚起。"""
    warnings: list[str] = []
    case_datasets = set(case["dataset_id"].dropna())
    control_datasets = set(control["dataset_id"].dropna())

    if case_datasets and control_datasets and not (case_datasets & control_datasets):
        warnings.append(
            "case と control が異なるデータセットに属しています。研究間では"
            "実験手技・ライブラリ調製・解析パイプラインの差（バッチ効果）が"
            "発現差として現れるため、この結果は探索的な参考値として扱ってください。"
        )
    elif len(case_datasets | control_datasets) > 1:
        warnings.append(
            "複数のデータセットにまたがる比較です。データセット間の技術的差異が"
            "結果に混入する可能性があります。"
        )

    case_units = set(case["unit"].dropna()) if "unit" in case else set()
    control_units = set(control["unit"].dropna()) if "unit" in control else set()
    if len(case_units | control_units) > 1:
        warnings.append(
            f"発現値の単位が混在しています（{', '.join(sorted(case_units | control_units))}）。"
            "単位の異なるデータの直接比較は解釈に注意が必要です。"
        )

    case_organs = set(case["organ"].dropna())
    control_organs = set(control["organ"].dropna())
    if case_organs and control_organs and case_organs != control_organs:
        warnings.append(
            f"case の臓器（{', '.join(sorted(case_organs))}）と control の臓器"
            f"（{', '.join(sorted(control_organs))}）が一致していません。"
        )

    if len(case) < 2 or len(control) < 2:
        warnings.append(
            "いずれかの群のサンプル数が 2 未満のため、検定は実施せず log2FC と"
            "効果量のみを返しています。"
        )

    if "batch" in case.columns:
        batches = set(pd.concat([case["batch"], control["batch"]]).dropna())
        if len(batches) > 1:
            warnings.append(f"複数のバッチが含まれます（{', '.join(sorted(map(str, batches)))}）。")

    return warnings


def run_compare(store: Store, request: CompareRequest) -> dict:
    """2 群比較を実行する。control 省略時は WT を自動採用する。"""
    if request.case.is_empty():
        raise HTTPException(
            status_code=400,
            detail="case のサンプル条件を指定してください（データセット・群・臓器、または sample_ids）。",
        )
    case = resolve_selection(store, request.case)
    if case.empty:
        raise HTTPException(status_code=400, detail="case の条件に一致するサンプルがありません。")

    control_auto = False
    if request.control is None or request.control.is_empty():
        control = store.default_controls(case)
        control_auto = True
        if control.empty:
            raise HTTPException(
                status_code=400,
                detail=(
                    "比較対象を自動選択できませんでした。case と同一データセット・"
                    "同一臓器に is_control=TRUE のサンプルがありません。"
                    "control を明示的に指定してください。"
                ),
            )
    else:
        control = resolve_selection(store, request.control)
        if control.empty:
            raise HTTPException(status_code=400, detail="control の条件に一致するサンプルがありません。")

    overlap = set(case["sample_id"]) & set(control["sample_id"])
    if overlap:
        raise HTTPException(
            status_code=400,
            detail=f"case と control に同じサンプルが含まれています: {', '.join(sorted(overlap))}",
        )

    case_ids = case["sample_id"].tolist()
    control_ids = control["sample_id"].tolist()

    case_matrix = store.matrix(case_ids)
    control_matrix = store.matrix(control_ids)
    if case_matrix.empty or control_matrix.empty:
        raise HTTPException(status_code=400, detail="選択されたサンプルに発現データがありません。")

    frame = stats.compare_groups(case_matrix, control_matrix, method=request.method)

    # 表示名として symbol を添える
    symbols = store.query(
        "SELECT gene_id, symbol FROM genes WHERE gene_id IN (SELECT unnest($ids))",
        {"ids": frame["gene_id"].tolist()},
    )
    if not symbols.empty:
        frame = frame.merge(symbols, on="gene_id", how="left")
    else:
        frame["symbol"] = frame["gene_id"]
    frame["symbol"] = frame["symbol"].fillna(frame["gene_id"])

    summary = stats.summarize(frame, request.log2fc_threshold, request.padj_threshold)

    return {
        "frame": frame,
        "summary": summary,
        "case_samples": case,
        "control_samples": control,
        "control_auto_selected": control_auto,
        "warnings": _batch_warnings(case, control),
        "method": request.method,
    }


def _matrix_for_selection(
    store: Store,
    selection: SampleSelection,
    n_top_genes: int,
    gene_ids: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """選択サンプルのマトリクスとサンプル情報を返す。

    条件が空の場合は全サンプルを対象にする（発現全体像を見る既定の入口）。
    """
    samples = resolve_selection(store, selection, allow_all=True)
    if samples.empty:
        raise HTTPException(status_code=400, detail="条件に一致するサンプルがありません。")
    sample_ids = samples["sample_id"].tolist()

    if gene_ids:
        genes = gene_ids
    else:
        genes = store.top_variable_genes(sample_ids, n_top_genes)
        if not genes:
            raise HTTPException(status_code=400, detail="選択されたサンプルに発現データがありません。")

    matrix = store.matrix(sample_ids, genes)
    if matrix.empty:
        raise HTTPException(status_code=400, detail="選択されたサンプルに発現データがありません。")
    # matrix に残った列だけを対象にする（発現データ未登録のサンプルを除外）
    samples = samples[samples["sample_id"].isin(matrix.columns)].reset_index(drop=True)
    return matrix, samples


def _series_by_sample(samples: pd.DataFrame, column: str) -> pd.Series:
    return pd.Series(samples[column].values, index=samples["sample_id"].values)


def run_pca(store: Store, request: PcaRequest) -> dict:
    matrix, samples = _matrix_for_selection(store, request.selection, request.n_top_genes)
    result = pca.run_pca(
        matrix,
        units=_series_by_sample(samples, "unit"),
        dataset_of=_series_by_sample(samples, "dataset_id"),
        n_components=request.n_components,
        scale_within_datasets=request.scale_within_datasets,
    )
    result["samples_meta"] = samples
    result["warnings"] = _selection_warnings(samples)
    return result


def run_heatmap(store: Store, request: HeatmapRequest) -> dict:
    matrix, samples = _matrix_for_selection(
        store, request.selection, request.n_top_genes, request.gene_ids
    )
    result = cluster.heatmap(
        matrix,
        units=_series_by_sample(samples, "unit"),
        dataset_of=_series_by_sample(samples, "dataset_id"),
        scale_within_datasets=request.scale_within_datasets,
        cluster_genes=request.cluster_genes,
        cluster_samples=request.cluster_samples,
    )
    result["samples_meta"] = samples
    result["warnings"] = _selection_warnings(samples)
    return result


def run_correlation(store: Store, request: CorrelationRequest) -> dict:
    matrix, samples = _matrix_for_selection(store, request.selection, request.n_top_genes)
    result = cluster.correlation(
        matrix, units=_series_by_sample(samples, "unit"), method=request.method
    )
    result["samples_meta"] = samples
    result["warnings"] = _selection_warnings(samples)
    return result


def _selection_warnings(samples: pd.DataFrame) -> list[str]:
    """単一集合に対する解析（PCA など）での注意喚起。"""
    warnings: list[str] = []
    datasets = set(samples["dataset_id"].dropna())
    units = set(samples["unit"].dropna()) if "unit" in samples else set()
    if len(datasets) > 1:
        warnings.append(
            "複数データセットのサンプルが含まれます。第 1 主成分が研究間の"
            "バッチ差を捉えることがあります。データセット内 z-score"
            "（scale_within_datasets）を有効にすると緩和できます。"
        )
    if len(units) > 1:
        warnings.append(f"発現値の単位が混在しています（{', '.join(sorted(units))}）。")
    return warnings
