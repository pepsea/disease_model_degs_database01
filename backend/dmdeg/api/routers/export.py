"""CSV ダウンロード。

画面表示は応答サイズの都合で件数を切ることがあるため、こちらは常に
全件を返す。表示と同じ関数を通すので数値が食い違わない。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from ...store import Store, get_store
from ..schemas import CompareRequest
from ..services import run_compare

router = APIRouter(prefix="/export", tags=["export"])

_CSV_COLUMNS = [
    "gene_id",
    "symbol",
    "log2fc",
    "mean_case",
    "mean_control",
    "base_mean",
    "pvalue",
    "padj",
    "effect_size",
    "n_case",
    "n_control",
]


def _csv_response(text: str, filename: str) -> PlainTextResponse:
    return PlainTextResponse(
        content=text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/compare")
def export_compare(request: CompareRequest, store: Store = Depends(get_store)) -> PlainTextResponse:
    result = run_compare(store, request)
    frame = result["frame"]
    columns = [c for c in _CSV_COLUMNS if c in frame.columns]
    return _csv_response(frame[columns].to_csv(index=False), "compare.csv")


@router.get("/gene")
def export_gene(
    gene: str = Query(min_length=1),
    dataset_id: str | None = None,
    organ: str | None = None,
    store: Store = Depends(get_store),
) -> PlainTextResponse:
    frame = store.gene_expression(gene, dataset_id=dataset_id, organ=organ)
    if frame.empty:
        raise HTTPException(status_code=404, detail=f"遺伝子 '{gene}' の発現データが見つかりません。")
    return _csv_response(frame.to_csv(index=False), f"{gene}_expression.csv")


@router.get("/degs")
def export_degs(comparison_id: str, store: Store = Depends(get_store)) -> PlainTextResponse:
    frame = store.get_degs(comparison_id)
    if frame.empty:
        raise HTTPException(status_code=404, detail=f"comparison '{comparison_id}' の DEG 表がありません。")
    return _csv_response(frame.to_csv(index=False), f"{comparison_id}_degs.csv")


@router.get("/samples")
def export_samples(
    dataset_id: str | None = None,
    organ: str | None = None,
    store: Store = Depends(get_store),
) -> PlainTextResponse:
    frame = store.list_samples(dataset_id=dataset_id, organ=organ)
    return _csv_response(frame.to_csv(index=False), "samples.csv")
