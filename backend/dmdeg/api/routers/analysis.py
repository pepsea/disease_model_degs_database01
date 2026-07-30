"""発現全体像と多変量解析（PCA / ヒートマップ / 相関クラスタリング）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...store import Store, get_store
from .. import serialize
from ..schemas import CorrelationRequest, HeatmapRequest, PcaRequest
from ..services import run_correlation, run_heatmap, run_pca

router = APIRouter(prefix="/analysis", tags=["analysis"])


def _with_meta(result: dict) -> dict:
    meta = result.pop("samples_meta", None)
    payload = serialize.clean(result)
    payload["samples_meta"] = serialize.records(meta) if meta is not None else []
    return payload


@router.post("/pca")
def pca(request: PcaRequest, store: Store = Depends(get_store)) -> dict:
    return _with_meta(run_pca(store, request))


@router.post("/heatmap")
def heatmap(request: HeatmapRequest, store: Store = Depends(get_store)) -> dict:
    return _with_meta(run_heatmap(store, request))


@router.post("/correlation")
def correlation(request: CorrelationRequest, store: Store = Depends(get_store)) -> dict:
    return _with_meta(run_correlation(store, request))
