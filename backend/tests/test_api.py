"""API のエンドツーエンド検証。

合成データに仕込んだ差が実際に上位に出るか、比較対象の WT 自動選択が
効いているか、といった「経路がつながっているか」を確認する。
"""

from __future__ import annotations

import pytest


def test_health_reports_ingested_counts(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["counts"]["samples"] == 22
    assert body["ingested_at"] is not None


def test_status_exposes_manifest_without_errors(client):
    body = client.get("/api/status").json()
    assert body["counts"]["datasets"] == 2
    assert [i for i in body["issues"] if i["level"] == "error"] == []


def test_facets_supply_selection_options(client):
    body = client.get("/api/facets").json()
    assert set(body["organs"]) == {"kidney", "liver"}
    assert "Mus musculus" in body["species"]
    assert {"RNA-seq", "microarray"} <= set(body["assays"])
    assert "代謝" in body["disease_categories"]


def test_models_include_dataset_counts(client):
    models = client.get("/api/models").json()
    by_id = {m["model_id"]: m for m in models}
    assert by_id["MDL_DB_DB"]["n_datasets"] == 1
    assert by_id["MDL_DB_DB"]["n_samples"] == 8


def test_datasets_list_and_organ_filter(client):
    everything = client.get("/api/datasets").json()
    assert {d["dataset_id"] for d in everything} == {"GSE900001", "GSE900002"}

    liver_only = client.get("/api/datasets", params={"organ": "liver"}).json()
    assert [d["dataset_id"] for d in liver_only] == ["GSE900001"]

    metabolic = client.get("/api/datasets", params={"disease_category": "代謝"}).json()
    assert [d["dataset_id"] for d in metabolic] == ["GSE900001"]

    searched = client.get("/api/datasets", params={"q": "Col4a3"}).json()
    assert [d["dataset_id"] for d in searched] == ["GSE900002"]


def test_dataset_detail_includes_samples_and_groups(client):
    body = client.get("/api/datasets/GSE900001").json()
    assert body["dataset"]["unit"] == "counts"
    assert len(body["samples"]) == 16
    groups = {(g["organ"], g["group_label"]): g for g in body["groups"]}
    assert groups[("kidney", "WT_kidney_16w")]["n_samples"] == 4
    assert groups[("kidney", "WT_kidney_16w")]["is_control"] is True
    assert groups[("kidney", "dbdb_kidney_16w")]["is_control"] is False


def test_unknown_dataset_returns_404(client):
    assert client.get("/api/datasets/GSE_NOPE").status_code == 404


def test_gene_search_prefers_exact_then_prefix(client):
    results = client.get("/api/genes/search", params={"q": "Lcn2"}).json()
    assert results[0]["gene_id"] == "Lcn2"
    assert results[0]["name"] == "lipocalin 2 (NGAL)"

    partial = client.get("/api/genes/search", params={"q": "Slc"}).json()
    assert {r["gene_id"] for r in partial} >= {"Slc34a1", "Slc12a1"}


def test_gene_expression_returns_points_and_summary(client):
    body = client.get(
        "/api/expression/gene", params={"gene": "Lcn2", "dataset_id": "GSE900001", "organ": "kidney"}
    ).json()
    assert len(body["points"]) == 8
    summary = {row["group_label"]: row for row in body["summary"]}
    assert summary["WT_kidney_16w"]["n"] == 4
    # 仕込みどおり疾患群で上昇している
    assert summary["dbdb_kidney_16w"]["mean"] > summary["WT_kidney_16w"]["mean"]


def test_gene_expression_rejects_bad_group_by(client):
    response = client.get("/api/expression/gene", params={"gene": "Lcn2", "group_by": "nonsense"})
    assert response.status_code == 400


def test_unknown_gene_returns_404(client):
    assert client.get("/api/expression/gene", params={"gene": "NotAGene"}).status_code == 404


def test_counts_dataset_is_cpm_normalized(client):
    """counts は CPM 換算されるため、生カウントとは異なる値が返る。"""
    body = client.get(
        "/api/expression/gene", params={"gene": "Actb", "dataset_id": "GSE900001"}
    ).json()
    point = body["points"][0]
    assert point["raw_value"] != pytest.approx(point["value"])
    assert body["units"] == ["counts"]


def test_log2_intensity_dataset_is_passed_through(client):
    """log2_intensity は正規化せず登録値をそのまま返す（二重変換しない）。"""
    body = client.get(
        "/api/expression/gene", params={"gene": "Actb", "dataset_id": "GSE900002"}
    ).json()
    point = body["points"][0]
    assert point["raw_value"] == pytest.approx(point["value"])
    assert body["units"] == ["log2_intensity"]


def test_gene_across_models_uses_within_dataset_controls(client):
    body = client.get(
        "/api/expression/gene/across-models", params={"gene": "Havcr1", "organ": "kidney"}
    ).json()
    rows = body["rows"]
    # 両データセットの疾患群が並ぶ
    assert {r["dataset_id"] for r in rows} == {"GSE900001", "GSE900002"}
    # 腎障害マーカーなのでどちらも上昇方向
    assert all(r["log2fc"] > 0 for r in rows)


# ---- 比較 -------------------------------------------------------------


def test_compare_auto_selects_wt_control(client):
    """control 省略時に同一データセット・同一臓器の WT が自動採用される。"""
    body = client.post(
        "/api/compare",
        json={"case": {"dataset_id": "GSE900001", "group_label": "dbdb_kidney_16w"}},
    ).json()
    assert body["control_auto_selected"] is True
    assert {s["group_label"] for s in body["control_samples"]} == {"WT_kidney_16w"}
    assert all(s["is_control"] for s in body["control_samples"])
    # 臓器をまたいでいない
    assert {s["organ"] for s in body["control_samples"]} == {"kidney"}


def test_compare_surfaces_spiked_genes_at_top(client, spiked_kidney):
    """仕込んだ差が上位に出ること。解析経路がつながっている証拠になる。"""
    body = client.post(
        "/api/compare",
        json={"case": {"dataset_id": "GSE900001", "group_label": "dbdb_kidney_16w"}},
    ).json()
    spiked = set(spiked_kidney["up"] + spiked_kidney["down"])
    top = [row["gene_id"] for row in body["rows"][: len(spiked) + 4]]
    # 仕込んだ 16 遺伝子の大半が上位に来る
    assert len(spiked & set(top)) >= len(spiked) - 2

    by_gene = {row["gene_id"]: row for row in body["rows"]}
    for gene in spiked_kidney["up"]:
        assert by_gene[gene]["log2fc"] > 1.0, gene
    for gene in spiked_kidney["down"]:
        assert by_gene[gene]["log2fc"] < -1.0, gene


def test_compare_housekeeping_genes_are_not_significant(client):
    """差を入れていない恒常発現遺伝子が偽陽性にならない。"""
    body = client.post(
        "/api/compare",
        json={"case": {"dataset_id": "GSE900001", "group_label": "dbdb_kidney_16w"}},
    ).json()
    by_gene = {row["gene_id"]: row for row in body["rows"]}
    for gene in ("Actb", "Gapdh", "Tbp", "Rpl13a"):
        assert abs(by_gene[gene]["log2fc"]) < 1.0, gene


def test_compare_explicit_control_overrides_default(client):
    """既定の WT ではない任意のデータを比較対象にできる。"""
    body = client.post(
        "/api/compare",
        json={
            "case": {"dataset_id": "GSE900001", "group_label": "dbdb_kidney_16w"},
            "control": {"dataset_id": "GSE900001", "group_label": "dbdb_liver_16w"},
        },
    ).json()
    assert body["control_auto_selected"] is False
    assert {s["group_label"] for s in body["control_samples"]} == {"dbdb_liver_16w"}


def test_compare_across_datasets_warns_about_batch(client):
    """研究をまたぐ比較ではバッチ交絡の警告が必ず付く。"""
    body = client.post(
        "/api/compare",
        json={
            "case": {"dataset_id": "GSE900002", "group_label": "Col4a3KO_kidney_8w"},
            "control": {"dataset_id": "GSE900001", "group_label": "WT_kidney_16w"},
        },
    ).json()
    warnings = " ".join(body["warnings"])
    assert "バッチ効果" in warnings
    assert "単位" in warnings  # counts と log2_intensity の混在も検出


def test_compare_within_dataset_has_no_batch_warning(client):
    body = client.post(
        "/api/compare",
        json={"case": {"dataset_id": "GSE900001", "group_label": "dbdb_kidney_16w"}},
    ).json()
    assert body["warnings"] == []


def test_compare_mismatched_organ_warns(client):
    body = client.post(
        "/api/compare",
        json={
            "case": {"dataset_id": "GSE900001", "group_label": "dbdb_kidney_16w"},
            "control": {"dataset_id": "GSE900001", "group_label": "WT_liver_16w"},
        },
    ).json()
    assert any("臓器" in w for w in body["warnings"])


def test_compare_rejects_empty_case(client):
    """case を空にしても全件比較が黙って走らない。"""
    response = client.post("/api/compare", json={"case": {}})
    assert response.status_code == 400
    assert "case" in response.json()["detail"]


def test_compare_rejects_overlapping_groups(client):
    response = client.post(
        "/api/compare",
        json={
            "case": {"dataset_id": "GSE900001", "organ": "kidney"},
            "control": {"dataset_id": "GSE900001", "group_label": "WT_kidney_16w"},
        },
    )
    assert response.status_code == 400
    assert "同じサンプル" in response.json()["detail"]


def test_compare_reports_summary_counts(client):
    body = client.post(
        "/api/compare",
        json={
            "case": {"dataset_id": "GSE900001", "group_label": "dbdb_kidney_16w"},
            "log2fc_threshold": 1.0,
            "padj_threshold": 0.05,
        },
    ).json()
    summary = body["summary"]
    assert summary["n_up"] > 0
    assert summary["n_down"] > 0
    assert summary["n_genes"] == body["n_genes_total"]


def test_compare_limit_truncates_but_reports_total(client):
    body = client.post(
        "/api/compare",
        json={"case": {"dataset_id": "GSE900001", "group_label": "dbdb_kidney_16w"}, "limit": 10},
    ).json()
    assert len(body["rows"]) == 10
    assert body["truncated"] is True
    assert body["n_genes_total"] > 10


def test_compare_by_individual_sample_ids(client):
    """個別サンプル選択でも比較できる。"""
    samples = client.get("/api/samples", params={"dataset_id": "GSE900001", "organ": "kidney"}).json()
    case_ids = [s["sample_id"] for s in samples if not s["is_control"]][:3]
    control_ids = [s["sample_id"] for s in samples if s["is_control"]][:3]
    body = client.post(
        "/api/compare",
        json={"case": {"sample_ids": case_ids}, "control": {"sample_ids": control_ids}},
    ).json()
    assert len(body["case_samples"]) == 3
    assert len(body["control_samples"]) == 3


# ---- 登録済み DEG 表 --------------------------------------------------


def test_registered_deg_table_available(client):
    body = client.get("/api/degs", params={"comparison_id": "CMP_GSE900001_KIDNEY_DBDB"}).json()
    assert body["comparison"]["organ"] == "kidney"
    genes = {row["gene_id"] for row in body["rows"][:20]}
    assert "Lcn2" in genes or "Havcr1" in genes


def test_degs_missing_table_explains_where_to_put_it(client):
    response = client.get("/api/degs", params={"comparison_id": "CMP_NOPE"})
    assert response.status_code == 404


def test_comparisons_flag_deg_table_presence(client):
    rows = client.get("/api/comparisons").json()
    assert rows[0]["has_deg_table"] is True


# ---- 解析 -------------------------------------------------------------


def test_pca_defaults_to_all_samples(client):
    body = client.post("/api/analysis/pca", json={"selection": {}, "n_top_genes": 300}).json()
    assert len(body["samples"]) == 22
    ratios = body["explained_variance_ratio"]
    assert ratios == sorted(ratios, reverse=True)
    # 複数データセットが混ざるので警告が出る
    assert any("バッチ" in w for w in body["warnings"])


def test_pca_separates_organs_within_one_dataset(client):
    """同一データセット内なら PC1 が臓器差を捉える。"""
    body = client.post(
        "/api/analysis/pca",
        json={"selection": {"dataset_id": "GSE900001"}, "n_top_genes": 300},
    ).json()
    meta = {row["sample_id"]: row["organ"] for row in body["samples_meta"]}
    pc1 = {row["sample_id"]: row["PC1"] for row in body["samples"]}
    kidney = [v for s, v in pc1.items() if meta[s] == "kidney"]
    liver = [v for s, v in pc1.items() if meta[s] == "liver"]
    assert max(kidney) < min(liver) or max(liver) < min(kidney)


def test_pca_within_dataset_scaling_flag_is_reported(client):
    body = client.post(
        "/api/analysis/pca",
        json={"selection": {}, "n_top_genes": 200, "scale_within_datasets": True},
    ).json()
    assert body["scaled_within_datasets"] is True


def test_heatmap_dimensions_match(client):
    body = client.post(
        "/api/analysis/heatmap",
        json={"selection": {"dataset_id": "GSE900001"}, "n_top_genes": 25},
    ).json()
    assert len(body["genes"]) == 25
    assert len(body["values"]) == 25
    assert all(len(row) == len(body["samples"]) for row in body["values"])


def test_heatmap_accepts_explicit_gene_list(client):
    genes = ["Havcr1", "Lcn2", "Umod", "Actb"]
    body = client.post(
        "/api/analysis/heatmap",
        json={"selection": {"dataset_id": "GSE900001", "organ": "kidney"}, "gene_ids": genes},
    ).json()
    assert set(body["genes"]) == set(genes)


def test_correlation_matrix_is_square(client):
    body = client.post(
        "/api/analysis/correlation",
        json={"selection": {"dataset_id": "GSE900001"}, "n_top_genes": 200},
    ).json()
    n = len(body["samples"])
    assert n == 16
    assert all(len(row) == n for row in body["matrix"])


def test_correlation_rejects_unknown_method(client):
    response = client.post(
        "/api/analysis/correlation",
        json={"selection": {"dataset_id": "GSE900001"}, "method": "kendall"},
    )
    assert response.status_code == 422  # pydantic が Literal で弾く


# ---- エクスポート -----------------------------------------------------


def test_export_compare_returns_full_csv(client):
    response = client.post(
        "/api/export/compare",
        json={"case": {"dataset_id": "GSE900001", "group_label": "dbdb_kidney_16w"}, "limit": 5},
    )
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    lines = response.text.strip().splitlines()
    assert lines[0].startswith("gene_id,symbol,log2fc")
    # limit は画面表示用。エクスポートは常に全遺伝子を返す
    assert len(lines) == 593


def test_export_gene_csv(client):
    response = client.get("/api/export/gene", params={"gene": "Lcn2"})
    assert response.status_code == 200
    assert "gene_id" in response.text.splitlines()[0]


def test_export_samples_csv(client):
    response = client.get("/api/export/samples", params={"dataset_id": "GSE900001"})
    assert len(response.text.strip().splitlines()) == 17


# ---- 認証 -------------------------------------------------------------


def test_basic_auth_enforced_when_configured(example_root, monkeypatch):
    from fastapi.testclient import TestClient

    from dmdeg import store as store_module
    from dmdeg.api.main import create_app

    monkeypatch.setenv("DMDEG_BASIC_AUTH", "curator:secret")
    store_module.reset_store()
    guarded = TestClient(create_app())

    assert guarded.get("/api/datasets").status_code == 401
    ok = guarded.get("/api/datasets", auth=("curator", "secret"))
    assert ok.status_code == 200
    assert guarded.get("/api/datasets", auth=("curator", "wrong")).status_code == 401
