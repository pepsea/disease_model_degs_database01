"""遺伝子ごとの発現量。"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query

from ...store import Store, get_store
from .. import serialize

router = APIRouter(tags=["expression"])


@router.get("/expression/gene")
def gene_expression(
    gene: str = Query(min_length=1),
    dataset_id: str | None = None,
    organ: str | None = None,
    group_by: str = Query(default="group_label"),
    store: Store = Depends(get_store),
) -> dict:
    """1 遺伝子の発現量を、群別プロット用の生値と要約統計で返す。"""
    allowed = {"group_label", "genotype", "organ", "dataset_id", "sex", "treatment", "batch"}
    if group_by not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"group_by に指定できるのは {', '.join(sorted(allowed))} です。",
        )

    frame = store.gene_expression(gene, dataset_id=dataset_id, organ=organ)
    if frame.empty:
        raise HTTPException(
            status_code=404,
            detail=f"遺伝子 '{gene}' の発現データが見つかりません（条件に一致するサンプルなし）。",
        )

    # 群ごとの要約。log 変換前の正規化値に対して算出する。
    grouped = (
        frame.groupby(["dataset_id", "organ", group_by], dropna=False)["value"]
        .agg(
            n="count",
            mean="mean",
            median="median",
            sd=lambda s: float(np.std(s, ddof=1)) if len(s) > 1 else np.nan,
            min="min",
            max="max",
        )
        .reset_index()
        .sort_values(["dataset_id", "organ", group_by], ignore_index=True)
    )

    gene_row = store.query(
        "SELECT * FROM genes WHERE lower(gene_id) = lower($gene) LIMIT 1", {"gene": gene}
    )

    return {
        "gene": serialize.row(gene_row.iloc[0]) if not gene_row.empty else {"gene_id": gene, "symbol": gene},
        "group_by": group_by,
        "points": serialize.records(frame),
        "summary": serialize.records(grouped),
        "units": sorted(set(frame["unit"].dropna())),
        "note": (
            "counts のデータセットは CPM 換算した値です。"
            "tpm / fpkm / log2_intensity は登録値をそのまま表示しています。"
        ),
    }


@router.get("/expression/gene/across-models")
def gene_across_models(
    gene: str = Query(min_length=1),
    organ: str | None = None,
    store: Store = Depends(get_store),
) -> dict:
    """モデル横断のフォレストプロット用に、各データセットの WT 比 log2FC を返す。

    各データセット内で「対照 (is_control=TRUE) vs それ以外の群」を計算するため、
    研究間のバッチ差の影響を受けにくい形で並べられる。
    """
    frame = store.gene_expression(gene, organ=organ)
    if frame.empty:
        raise HTTPException(status_code=404, detail=f"遺伝子 '{gene}' の発現データが見つかりません。")

    rows = []
    for (dataset_id, organ_name), block in frame.groupby(["dataset_id", "organ"], dropna=False):
        controls = block[block["is_control"]]
        if controls.empty:
            continue
        control_mean = float(controls["value"].mean())
        for group_label, group in block[~block["is_control"]].groupby("group_label", dropna=False):
            case_mean = float(group["value"].mean())
            rows.append(
                {
                    "dataset_id": dataset_id,
                    "organ": organ_name,
                    "group_label": group_label,
                    "model_name": group["model_name"].iloc[0],
                    "disease_category": group["disease_category"].iloc[0],
                    "n_case": int(len(group)),
                    "n_control": int(len(controls)),
                    "mean_case": case_mean,
                    "mean_control": control_mean,
                    "log2fc": float(np.log2((case_mean + 1.0) / (control_mean + 1.0))),
                    "unit": group["unit"].iloc[0],
                }
            )

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=(
                f"遺伝子 '{gene}' について WT 比を計算できる組み合わせがありません。"
                " 各データセットに is_control=TRUE のサンプルが必要です。"
            ),
        )

    rows.sort(key=lambda r: r["log2fc"], reverse=True)
    return {"gene": gene, "rows": serialize.clean(rows)}
