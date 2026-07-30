"""2 群比較（volcano / MA / DEG 表）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...store import Store, get_store
from .. import serialize
from ..schemas import CompareRequest
from ..services import run_compare

router = APIRouter(tags=["compare"])


@router.post("/compare")
def compare(request: CompareRequest, store: Store = Depends(get_store)) -> dict:
    """case と control を比較する。control 省略時は同一データセット・同一臓器の WT を自動採用。"""
    result = run_compare(store, request)
    frame = result["frame"]

    total = int(len(frame))
    truncated = False
    if request.limit is not None and total > request.limit:
        # 有意な側から順に並んでいるため先頭を返す
        frame = frame.head(request.limit)
        truncated = True

    return {
        "rows": serialize.records(frame),
        "summary": serialize.clean(result["summary"]),
        "method": result["method"],
        "control_auto_selected": result["control_auto_selected"],
        "case_samples": serialize.records(result["case_samples"]),
        "control_samples": serialize.records(result["control_samples"]),
        "warnings": result["warnings"],
        "n_genes_total": total,
        "truncated": truncated,
        "note": (
            "この結果は Welch の t 検定（または Mann-Whitney U）と BH 補正による探索用の統計です。"
            "確定的な DEG 判定には DESeq2 等の結果を data/degs/ に登録してください。"
        ),
    }
