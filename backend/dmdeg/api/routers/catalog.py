"""カタログ系エンドポイント（ファセット選択肢の供給）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ...store import Store, get_store
from .. import serialize

router = APIRouter(tags=["catalog"])


@router.get("/status")
def status(store: Store = Depends(get_store)) -> dict:
    """収載状況と ingest 時の警告。UI の「データ状態」表示に使う。"""
    manifest = store.manifest()
    return serialize.clean(manifest)


@router.get("/facets")
def facets(store: Store = Depends(get_store)) -> dict:
    return serialize.clean(store.facets())


@router.get("/models")
def models(store: Store = Depends(get_store)) -> list[dict]:
    return serialize.records(store.list_models())


@router.get("/datasets")
def datasets(
    species: str | None = None,
    model_id: str | None = None,
    organ: str | None = None,
    disease_category: str | None = None,
    assay: str | None = None,
    q: str | None = None,
    store: Store = Depends(get_store),
) -> list[dict]:
    return serialize.records(
        store.list_datasets(
            species=species,
            model_id=model_id,
            organ=organ,
            disease_category=disease_category,
            assay=assay,
            q=q,
        )
    )


@router.get("/datasets/{dataset_id}")
def dataset_detail(dataset_id: str, store: Store = Depends(get_store)) -> dict:
    dataset = store.get_dataset(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' は登録されていません。")
    samples = store.list_samples(dataset_id=dataset_id)
    comparisons = store.list_comparisons(dataset_id=dataset_id)
    groups = (
        samples.groupby(["organ", "group_label"])
        .agg(
            n_samples=("sample_id", "count"),
            is_control=("is_control", "max"),
            genotype=("genotype", "first"),
        )
        .reset_index()
        if not samples.empty
        else samples
    )
    return {
        "dataset": serialize.row(dataset),
        "samples": serialize.records(samples),
        "groups": serialize.records(groups),
        "comparisons": serialize.records(comparisons),
    }


@router.get("/samples")
def samples(
    dataset_id: str | None = None,
    organ: str | None = None,
    genotype: str | None = None,
    model_id: str | None = None,
    store: Store = Depends(get_store),
) -> list[dict]:
    return serialize.records(
        store.list_samples(dataset_id=dataset_id, organ=organ, genotype=genotype, model_id=model_id)
    )


@router.get("/comparisons")
def comparisons(dataset_id: str | None = None, store: Store = Depends(get_store)) -> list[dict]:
    return serialize.records(store.list_comparisons(dataset_id=dataset_id))


@router.get("/degs")
def degs(comparison_id: str, store: Store = Depends(get_store)) -> dict:
    """登録済み DEG 表（厳密解析結果）を返す。"""
    comparison = store.list_comparisons()
    matched = comparison[comparison["comparison_id"] == comparison_id]
    if matched.empty:
        raise HTTPException(status_code=404, detail=f"comparison '{comparison_id}' は登録されていません。")
    frame = store.get_degs(comparison_id)
    if frame.empty:
        raise HTTPException(
            status_code=404,
            detail=(
                f"comparison '{comparison_id}' に対応する DEG 表が未登録です。"
                f" data/degs/{comparison_id}.csv を配置してください。"
            ),
        )
    return {
        "comparison": serialize.row(matched.iloc[0]),
        "rows": serialize.records(frame),
    }


@router.get("/genes/search")
def gene_search(
    q: str = Query(min_length=1),
    species: str | None = None,
    limit: int = Query(default=30, ge=1, le=200),
    store: Store = Depends(get_store),
) -> list[dict]:
    return serialize.records(store.search_genes(q, species=species, limit=limit))
