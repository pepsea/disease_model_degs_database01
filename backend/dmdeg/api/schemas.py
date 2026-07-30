"""リクエスト/レスポンスのスキーマ。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..config import DEFAULT_TOP_VARIABLE_GENES


class SampleSelection(BaseModel):
    """比較ビルダーが組み立てるサンプル集合の指定。

    `sample_ids` を渡せば個別サンプル指定、それ以外の条件を渡せば
    「データセット → 臓器 → 群」での指定になる。両方併用も可。
    """

    sample_ids: list[str] | None = None
    dataset_id: str | None = None
    group_label: str | None = None
    organ: str | None = None
    genotype: str | None = None

    def is_empty(self) -> bool:
        return not any(
            [self.sample_ids, self.dataset_id, self.group_label, self.organ, self.genotype]
        )


class CompareRequest(BaseModel):
    case: SampleSelection
    # 省略すると case と同一 dataset × organ の is_control=TRUE（=WT）を自動採用する
    control: SampleSelection | None = None
    method: Literal["welch", "mannwhitney"] = "welch"
    log2fc_threshold: float = 1.0
    padj_threshold: float = 0.05
    # 応答サイズを抑えるための上限。null で全遺伝子。
    limit: int | None = 5000


class PcaRequest(BaseModel):
    selection: SampleSelection
    n_top_genes: int = Field(default=DEFAULT_TOP_VARIABLE_GENES, ge=10, le=20000)
    n_components: int = Field(default=5, ge=2, le=10)
    scale_within_datasets: bool = False


class HeatmapRequest(BaseModel):
    selection: SampleSelection
    n_top_genes: int = Field(default=50, ge=2, le=500)
    gene_ids: list[str] | None = None
    scale_within_datasets: bool = False
    cluster_genes: bool = True
    cluster_samples: bool = True


class CorrelationRequest(BaseModel):
    selection: SampleSelection
    method: Literal["pearson", "spearman"] = "spearman"
    n_top_genes: int = Field(default=DEFAULT_TOP_VARIABLE_GENES, ge=10, le=20000)
