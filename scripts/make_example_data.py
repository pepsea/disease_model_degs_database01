#!/usr/bin/env python3
"""動作確認用の合成データを生成する。

    python scripts/make_example_data.py              # example_data/ に書く
    python scripts/make_example_data.py --out /tmp/x # 別の場所に書く
    python scripts/make_example_data.py --force      # 既存データを上書き

出力先を `data/` ではなく `example_data/` にしているのは、実データの登録先に
合成データが混ざらないようにするため。デモ時は環境変数で登録先を切り替える。

    DMDEG_DATA_DIR=example_data DMDEG_BUILD_DIR=build_example python -m dmdeg.ingest

意図的に差を仕込んだ遺伝子を `SPIKES` に定義してあり、テストは
「その遺伝子が /api/compare の上位に出るか」で解析経路を検証する。
実データではないので、生物学的な解釈には使えない。
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

RNG_SEED = 20260730

# 恒常的に発現する遺伝子（差を入れない）
HOUSEKEEPING = ["Actb", "Gapdh", "Tbp", "Rpl13a", "B2m", "Ppia", "Hprt"]

# 腎障害・線維化マーカー / 尿細管成熟マーカー / 脂肪肝マーカー
KIDNEY_INJURY_UP = ["Havcr1", "Lcn2", "Timp1", "Col1a1", "Fn1", "Ccl2", "Spp1", "Vim", "Adgre1", "Tgfb1"]
KIDNEY_TUBULE_DOWN = ["Slc34a1", "Lrp2", "Umod", "Kap", "Slc12a1", "Aqp2"]
LIVER_STEATOSIS_UP = ["Cd36", "Scd1", "Mogat1", "Cidec", "Saa3", "Col1a1"]
LIVER_OXIDATION_DOWN = ["Cyp7b1", "Acox1", "Hmgcs2", "Ppargc1a"]

GENE_NAMES = {
    "Havcr1": "hepatitis A virus cellular receptor 1 (Kim-1)",
    "Lcn2": "lipocalin 2 (NGAL)",
    "Umod": "uromodulin",
    "Slc34a1": "solute carrier family 34 member 1",
    "Col1a1": "collagen type I alpha 1 chain",
    "Cd36": "CD36 molecule",
    "Actb": "actin beta",
    "Gapdh": "glyceraldehyde-3-phosphate dehydrogenase",
}

# (dataset_id, organ) -> {"up": [...], "down": [...]}
SPIKES: dict[tuple[str, str], dict[str, list[str]]] = {
    ("GSE900001", "kidney"): {"up": KIDNEY_INJURY_UP, "down": KIDNEY_TUBULE_DOWN},
    ("GSE900001", "liver"): {"up": LIVER_STEATOSIS_UP, "down": LIVER_OXIDATION_DOWN},
    ("GSE900002", "kidney"): {"up": KIDNEY_INJURY_UP[:6], "down": KIDNEY_TUBULE_DOWN[:4]},
}

N_FILLER_GENES = 560

MODELS = [
    {
        "model_id": "MDL_DB_DB",
        "model_name": "db/db マウス",
        "species": "Mus musculus",
        "modality": "spontaneous",
        "disease_category": "代謝",
        "strain": "C57BLKS/J",
        "target_gene": "Lepr",
        "description": "レプチン受容体機能欠損による 2 型糖尿病モデル（合成例データ）",
        "reference_url": "",
    },
    {
        "model_id": "MDL_COL4A3_KO",
        "model_name": "Col4a3 KO マウス",
        "species": "Mus musculus",
        "modality": "KO",
        "disease_category": "腎",
        "strain": "C57BL/6J",
        "target_gene": "Col4a3",
        "description": "アルポート症候群モデル（合成例データ）",
        "reference_url": "",
    },
    {
        "model_id": "MDL_WT",
        "model_name": "野生型対照",
        "species": "Mus musculus",
        "modality": "none",
        "disease_category": "対照",
        "strain": "C57BL/6J",
        "target_gene": "",
        "description": "無処置の野生型（合成例データ）",
        "reference_url": "",
    },
]

DATASETS = [
    {
        "dataset_id": "GSE900001",
        "title": "db/db マウスの腎臓・肝臓 RNA-seq（合成例データ）",
        "model_id": "MDL_DB_DB",
        "species": "Mus musculus",
        "assay": "RNA-seq",
        "unit": "counts",
        "gene_id_type": "symbol",
        "platform": "GPL24247",
        "duplicate_policy": "max",
        "pmid": "",
        "geo_url": "",
        "submitted_by": "example",
        "notes": "動作確認用の合成データ。生物学的解釈には使えない。",
    },
    {
        "dataset_id": "GSE900002",
        "title": "Col4a3 KO マウスの腎臓マイクロアレイ（合成例データ）",
        "model_id": "MDL_COL4A3_KO",
        "species": "Mus musculus",
        "assay": "microarray",
        "unit": "log2_intensity",
        "gene_id_type": "symbol",
        "platform": "GPL6246",
        "duplicate_policy": "max",
        "pmid": "",
        "geo_url": "",
        "submitted_by": "example",
        "notes": "単位が log2_intensity の例。二重 log 変換されないことの確認用。",
    },
]

# dataset_id -> [(organ, group_label, genotype, is_control, model_id, n)]
GROUPS: dict[str, list[tuple[str, str, str, bool, str, int]]] = {
    "GSE900001": [
        ("kidney", "WT_kidney_16w", "WT", True, "MDL_WT", 4),
        ("kidney", "dbdb_kidney_16w", "mutant", False, "MDL_DB_DB", 4),
        ("liver", "WT_liver_16w", "WT", True, "MDL_WT", 4),
        ("liver", "dbdb_liver_16w", "mutant", False, "MDL_DB_DB", 4),
    ],
    "GSE900002": [
        ("kidney", "WT_kidney_8w", "WT", True, "MDL_WT", 3),
        ("kidney", "Col4a3KO_kidney_8w", "mutant", False, "MDL_COL4A3_KO", 3),
    ],
}

COMPARISONS = [
    {
        "comparison_id": "CMP_GSE900001_KIDNEY_DBDB",
        "dataset_id": "GSE900001",
        "case_group_label": "dbdb_kidney_16w",
        "control_group_label": "WT_kidney_16w",
        "organ": "kidney",
        "method": "example_precomputed",
        "label": "db/db vs WT（腎, 16週）※合成例の登録済み DEG 表",
    }
]


def build_gene_list() -> list[str]:
    """マーカー遺伝子 + 一般名の埋め遺伝子。順序を固定する。"""
    markers: list[str] = []
    for name in (
        HOUSEKEEPING
        + KIDNEY_INJURY_UP
        + KIDNEY_TUBULE_DOWN
        + LIVER_STEATOSIS_UP
        + LIVER_OXIDATION_DOWN
    ):
        if name not in markers:
            markers.append(name)
    filler = [f"Gm{10000 + i}" for i in range(N_FILLER_GENES)]
    return markers + filler


def generate_matrix(
    dataset_id: str,
    unit: str,
    genes: list[str],
    samples: list[dict],
    rng: np.random.Generator,
) -> dict[str, list]:
    """遺伝子 × サンプルの発現値を作る。

    counts は負の二項分布（Gamma-Poisson 混合）で、log2_intensity は
    log 空間の正規分布で生成する。単位ごとに素性の違う値を出すことで、
    正規化処理の分岐が実際に効いているかを確認できる。
    """
    n_genes = len(genes)
    gene_index = {g: i for i, g in enumerate(genes)}

    # 遺伝子ごとのベース発現量（対数正規で右に裾を引かせる）
    base = rng.lognormal(mean=4.0, sigma=1.6, size=n_genes) + 5.0
    # ハウスキーピングは高発現に固定
    for name in HOUSEKEEPING:
        base[gene_index[name]] = rng.uniform(8000, 20000)

    organs = sorted({s["organ"] for s in samples})

    # 臓器プロファイルと疾患効果は、サンプルごとではなく
    # (臓器) / (臓器, 疾患) ごとに 1 回だけ引く。サンプルごとに引き直すと
    # 同じ臓器・同じ群のサンプルが共通の signature を持たなくなり、
    # PCA でまとまらず、群間の差も検出しにくくなる。
    # サンプル間のばらつきは下の NB ノイズが担う。
    organ_profiles: dict[str, np.ndarray] = {}
    for index, organ in enumerate(organs):
        # 先頭の臓器を基準にして、それ以外に固定のずれを与える
        organ_profiles[organ] = (
            np.zeros(n_genes) if index == 0 else rng.normal(0.0, 0.35, size=n_genes)
        )

    disease_effects: dict[str, np.ndarray] = {}
    for organ in organs:
        spike = SPIKES.get((dataset_id, organ), {"up": [], "down": []})
        effect = np.zeros(n_genes)
        for name in spike["up"]:
            effect[gene_index[name]] = rng.uniform(2.2, 3.8)
        for name in spike["down"]:
            effect[gene_index[name]] = -rng.uniform(1.8, 3.0)
        disease_effects[organ] = effect

    columns: dict[str, list] = {}
    for sample in samples:
        organ = sample["organ"]
        effect = np.zeros(n_genes) if sample["is_control"] else disease_effects[organ]
        mean = base * np.exp2(effect + organ_profiles[organ])

        if unit == "counts":
            # ライブラリサイズを個体ごとに 0.6〜1.6 倍ばらつかせ、CPM 換算の
            # 効果が確認できるようにする
            library_factor = rng.uniform(0.6, 1.6)
            scaled = mean * library_factor
            # NB: Gamma で平均をばらつかせてから Poisson を引く。
            # 実際のマウス RNA-seq より小さい分散にしてあるのは、仕込んだ差が
            # FDR 補正後もはっきり有意に出て、画面とテストの両方で判定が
            # 安定するようにするため。realistic さより再現性を優先している。
            dispersion = 0.05
            shape = 1.0 / dispersion
            gamma = rng.gamma(shape=shape, scale=scaled / shape)
            values = rng.poisson(gamma).astype(np.int64)
            columns[sample["sample_id"]] = values.tolist()
        else:
            # マイクロアレイ相当: log2 強度 + 加法ノイズ
            logged = np.log2(mean + 1.0) + rng.normal(0.0, 0.25, size=n_genes)
            columns[sample["sample_id"]] = np.round(logged, 4).tolist()

    return columns


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def has_existing_data(out: Path) -> bool:
    """テンプレート（ヘッダのみ）ではない実データが既にあるか。"""
    datasets = out / "datasets.csv"
    if not datasets.exists():
        return False
    with datasets.open(encoding="utf-8") as handle:
        rows = [r for r in csv.reader(handle) if r and any(c.strip() for c in r)]
    return len(rows) > 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="動作確認用の合成データを生成する")
    parser.add_argument(
        "--out", type=Path, default=None, help="出力先ディレクトリ（既定: リポジトリの example_data/）"
    )
    parser.add_argument("--force", action="store_true", help="既存データがあっても上書きする")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    out = args.out if args.out is not None else repo_root / "example_data"

    if has_existing_data(out) and not args.force:
        print(
            f"{out} には既にデータが登録されています。上書きするには --force を付けてください。",
            file=sys.stderr,
        )
        return 1

    # 統制語彙は data_dir 配下から読まれるため、出力先にも複製しておく。
    # これが無いと語彙照合が丸ごとスキップされ、表記ゆれ警告が出なくなる。
    vocab_src = repo_root / "data" / "vocab"
    vocab_dst = out / "vocab"
    if vocab_src.exists() and not vocab_dst.exists():
        import shutil

        shutil.copytree(vocab_src, vocab_dst)

    rng = np.random.default_rng(RNG_SEED)
    genes = build_gene_list()

    # ---- samples ----
    sample_rows: list[list] = []
    samples_by_dataset: dict[str, list[dict]] = {}
    counter = 9000000
    for dataset_id, groups in GROUPS.items():
        collected: list[dict] = []
        for organ, group_label, genotype, is_control, model_id, n in groups:
            for replicate in range(1, n + 1):
                counter += 1
                sample_id = f"GSM{counter}"
                sex = "male" if replicate % 2 else "female"
                collected.append(
                    {
                        "sample_id": sample_id,
                        "organ": organ,
                        "group_label": group_label,
                        "is_control": is_control,
                    }
                )
                sample_rows.append(
                    [
                        sample_id,
                        dataset_id,
                        model_id,
                        group_label,
                        genotype,
                        "TRUE" if is_control else "FALSE",
                        organ,
                        "renal cortex" if organ == "kidney" else "",
                        sex,
                        16 if dataset_id == "GSE900001" else 8,
                        "none",
                        replicate,
                        f"{dataset_id}_B1",
                    ]
                )
        samples_by_dataset[dataset_id] = collected

    write_csv(
        out / "samples.csv",
        [
            "sample_id",
            "dataset_id",
            "model_id",
            "group_label",
            "genotype",
            "is_control",
            "organ",
            "tissue_detail",
            "sex",
            "age_weeks",
            "treatment",
            "replicate",
            "batch",
        ],
        sample_rows,
    )

    # ---- models / datasets ----
    model_header = [
        "model_id",
        "model_name",
        "species",
        "strain",
        "modality",
        "target_gene",
        "disease_category",
        "description",
        "reference_url",
    ]
    write_csv(out / "models.csv", model_header, [[m[c] for c in model_header] for m in MODELS])

    dataset_header = [
        "dataset_id",
        "title",
        "model_id",
        "species",
        "assay",
        "unit",
        "gene_id_type",
        "platform",
        "duplicate_policy",
        "pmid",
        "geo_url",
        "submitted_by",
        "notes",
    ]
    write_csv(out / "datasets.csv", dataset_header, [[d[c] for c in dataset_header] for d in DATASETS])

    # ---- expression ----
    matrices: dict[str, dict[str, list]] = {}
    for dataset in DATASETS:
        dataset_id = dataset["dataset_id"]
        columns = generate_matrix(
            dataset_id, dataset["unit"], genes, samples_by_dataset[dataset_id], rng
        )
        matrices[dataset_id] = columns
        sample_ids = list(columns.keys())
        rows = [[gene] + [columns[s][i] for s in sample_ids] for i, gene in enumerate(genes)]
        write_csv(out / "expression" / f"{dataset_id}.csv", ["gene_id"] + sample_ids, rows)

    # ---- genes ----
    write_csv(
        out / "genes.csv",
        ["gene_id", "symbol", "name", "species", "ensembl", "entrez", "biotype", "synonyms"],
        [
            [gene, gene, GENE_NAMES.get(gene, ""), "Mus musculus", "", "", "protein_coding", ""]
            for gene in genes
        ],
    )

    # ---- comparisons ----
    comparison_header = [
        "comparison_id",
        "dataset_id",
        "case_group_label",
        "control_group_label",
        "organ",
        "method",
        "label",
    ]
    write_csv(
        out / "comparisons.csv",
        comparison_header,
        [[c[col] for col in comparison_header] for c in COMPARISONS],
    )

    # ---- 登録済み DEG 表（「厳密解析結果」タブの動作確認用） ----
    # 本来は DESeq2 等の外部出力を置く場所。ここでは合成データから
    # 単純な群平均比と Welch 検定で作った例を置く。
    _write_example_degs(out, genes, matrices, samples_by_dataset)

    print(f"合成データを {out} に生成しました。")
    print(f"  遺伝子 {len(genes)} / データセット {len(DATASETS)} / サンプル {len(sample_rows)}")
    print("  次に実行:")
    print(f"    DMDEG_DATA_DIR={out.name} DMDEG_BUILD_DIR=build_example python -m dmdeg.ingest")
    return 0


def _write_example_degs(
    out: Path,
    genes: list[str],
    matrices: dict[str, dict[str, list]],
    samples_by_dataset: dict[str, list[dict]],
) -> None:
    from scipy import stats as sp_stats

    comparison = COMPARISONS[0]
    dataset_id = comparison["dataset_id"]
    columns = matrices[dataset_id]
    samples = samples_by_dataset[dataset_id]

    case_ids = [s["sample_id"] for s in samples if s["group_label"] == comparison["case_group_label"]]
    control_ids = [
        s["sample_id"] for s in samples if s["group_label"] == comparison["control_group_label"]
    ]

    case = np.array([columns[s] for s in case_ids], dtype=float).T
    control = np.array([columns[s] for s in control_ids], dtype=float).T

    # CPM 換算してから比較する（登録側でも正規化済みの値を使う想定）
    case = case / case.sum(axis=0, keepdims=True) * 1e6
    control = control / control.sum(axis=0, keepdims=True) * 1e6

    mean_case = case.mean(axis=1)
    mean_control = control.mean(axis=1)
    log2fc = np.log2((mean_case + 1.0) / (mean_control + 1.0))
    pvalue = sp_stats.ttest_ind(
        np.log2(case + 1.0), np.log2(control + 1.0), axis=1, equal_var=False
    ).pvalue

    order = np.argsort(pvalue)
    ranked = pvalue[order]
    n = ranked.size
    adjusted = np.minimum.accumulate((ranked * n / np.arange(1, n + 1))[::-1])[::-1]
    padj = np.empty(n)
    padj[order] = np.clip(adjusted, 0, 1)

    rows = [
        [
            gene,
            round(float(log2fc[i]), 4),
            f"{pvalue[i]:.6g}",
            f"{padj[i]:.6g}",
            round(float((mean_case[i] + mean_control[i]) / 2), 3),
        ]
        for i, gene in enumerate(genes)
    ]
    write_csv(
        out / "degs" / f"{comparison['comparison_id']}.csv",
        ["gene_id", "log2fc", "pvalue", "padj", "base_mean"],
        rows,
    )


if __name__ == "__main__":
    raise SystemExit(main())
