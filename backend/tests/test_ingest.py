"""取り込み検証の挙動。

重視しているのは「壊れた CSV に対してエラーを 1 件目で止めず、行番号付きで
全件列挙する」こと。キュレーターが一度の実行で全部直せる状態にするため。
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

from dmdeg import config, ingest, store

HEADERS = {
    "models.csv": [
        "model_id", "model_name", "species", "strain", "modality",
        "target_gene", "disease_category", "description", "reference_url",
    ],
    "datasets.csv": [
        "dataset_id", "title", "model_id", "species", "assay", "unit", "gene_id_type",
        "platform", "duplicate_policy", "pmid", "geo_url", "submitted_by", "notes",
    ],
    "samples.csv": [
        "sample_id", "dataset_id", "model_id", "group_label", "genotype", "is_control",
        "organ", "tissue_detail", "sex", "age_weeks", "treatment", "replicate", "batch",
    ],
}


def _write(path: Path, rows: list[list], header: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


@pytest.fixture()
def scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """最小構成で妥当なデータセットを作り、テストごとに壊す土台にする。"""
    data = tmp_path / "data"
    monkeypatch.setenv("DMDEG_DATA_DIR", str(data))
    monkeypatch.setenv("DMDEG_BUILD_DIR", str(tmp_path / "build"))
    store.reset_store()

    _write(data / "models.csv", [["M1", "モデル1", "Mus musculus", "", "KO", "Trp53", "腎", "", ""]], HEADERS["models.csv"])
    _write(
        data / "datasets.csv",
        [["GSE1", "研究1", "M1", "Mus musculus", "RNA-seq", "counts", "symbol", "", "max", "", "", "", ""]],
        HEADERS["datasets.csv"],
    )
    _write(
        data / "samples.csv",
        [
            ["S1", "GSE1", "M1", "WT", "WT", "TRUE", "kidney", "", "male", "8", "", "1", "B1"],
            ["S2", "GSE1", "M1", "WT", "WT", "TRUE", "kidney", "", "male", "8", "", "2", "B1"],
            ["S3", "GSE1", "M1", "KO", "mutant", "FALSE", "kidney", "", "male", "8", "", "1", "B1"],
            ["S4", "GSE1", "M1", "KO", "mutant", "FALSE", "kidney", "", "male", "8", "", "2", "B1"],
        ],
        HEADERS["samples.csv"],
    )
    _write(
        data / "expression" / "GSE1.csv",
        [["GeneA", 10, 12, 100, 110], ["GeneB", 50, 55, 20, 25]],
        ["gene_id", "S1", "S2", "S3", "S4"],
    )
    return data


def test_valid_minimal_dataset_ingests(scratch: Path):
    log, manifest = ingest.ingest(write=True)
    assert not log.has_errors, log.report()
    assert manifest["counts"]["samples"] == 4
    assert config.manifest_path().exists()
    assert (config.expression_parquet_dir() / "dataset_id=GSE1" / "part.parquet").exists()


def test_broken_references_are_all_reported(scratch: Path):
    """参照切れが複数あっても 1 件目で止まらず全件出る。"""
    _write(
        scratch / "samples.csv",
        [
            ["S1", "GSE_MISSING", "M1", "WT", "WT", "TRUE", "kidney", "", "", "", "", "", ""],
            ["S2", "GSE1", "M_MISSING", "WT", "WT", "TRUE", "kidney", "", "", "", "", "", ""],
            ["S3", "GSE_ALSO_MISSING", "M1", "KO", "mutant", "FALSE", "kidney", "", "", "", "", "", ""],
        ],
        HEADERS["samples.csv"],
    )
    log, _ = ingest.ingest(write=True)
    messages = [i.message for i in log.errors]
    assert any("GSE_MISSING" in m for m in messages)
    assert any("M_MISSING" in m for m in messages)
    assert any("GSE_ALSO_MISSING" in m for m in messages)
    # 行番号が付いていること（2 行目以降を指す）
    assert {i.row for i in log.errors if i.file == "samples.csv"} >= {2, 3, 4}


def test_missing_required_column_reported(scratch: Path):
    header = [c for c in HEADERS["samples.csv"] if c != "organ"]
    _write(
        scratch / "samples.csv",
        [["S1", "GSE1", "M1", "WT", "WT", "TRUE", "", "male", "8", "", "1", "B1"]],
        header,
    )
    log, _ = ingest.ingest(write=True)
    assert any("organ" in i.message and "必須列" in i.message for i in log.errors)


def test_blank_required_value_reported_with_row(scratch: Path):
    _write(
        scratch / "samples.csv",
        [
            ["S1", "GSE1", "M1", "WT", "WT", "TRUE", "kidney", "", "", "", "", "", ""],
            ["S2", "GSE1", "M1", "", "WT", "TRUE", "kidney", "", "", "", "", "", ""],
        ],
        HEADERS["samples.csv"],
    )
    log, _ = ingest.ingest(write=True)
    blank = [i for i in log.errors if i.column == "group_label"]
    assert blank and blank[0].row == 3


def test_duplicate_primary_key_reported(scratch: Path):
    _write(
        scratch / "samples.csv",
        [
            ["S1", "GSE1", "M1", "WT", "WT", "TRUE", "kidney", "", "", "", "", "", ""],
            ["S1", "GSE1", "M1", "KO", "mutant", "FALSE", "kidney", "", "", "", "", "", ""],
        ],
        HEADERS["samples.csv"],
    )
    log, _ = ingest.ingest(write=True)
    assert any("重複" in i.message and "S1" in i.message for i in log.errors)


def test_invalid_unit_is_error(scratch: Path):
    """unit は正規化処理が分岐するため統制必須（警告ではなくエラー）。"""
    _write(
        scratch / "datasets.csv",
        [["GSE1", "研究1", "M1", "Mus musculus", "RNA-seq", "RPKM", "symbol", "", "max", "", "", "", ""]],
        HEADERS["datasets.csv"],
    )
    log, _ = ingest.ingest(write=True)
    assert any(i.column == "unit" and "RPKM" in i.message for i in log.errors)


def test_unparseable_boolean_is_error(scratch: Path):
    _write(
        scratch / "samples.csv",
        [["S1", "GSE1", "M1", "WT", "WT", "maybe", "kidney", "", "", "", "", "", ""]],
        HEADERS["samples.csv"],
    )
    log, _ = ingest.ingest(write=True)
    assert any(i.column == "is_control" for i in log.errors)


def test_boolean_synonyms_accepted(scratch: Path):
    """TRUE/FALSE 以外の一般的な表記も受理する。"""
    _write(
        scratch / "samples.csv",
        [
            ["S1", "GSE1", "M1", "WT", "WT", "yes", "kidney", "", "", "", "", "", ""],
            ["S2", "GSE1", "M1", "WT", "WT", "1", "kidney", "", "", "", "", "", ""],
            ["S3", "GSE1", "M1", "KO", "mutant", "no", "kidney", "", "", "", "", "", ""],
            ["S4", "GSE1", "M1", "KO", "mutant", "0", "kidney", "", "", "", "", "", ""],
        ],
        HEADERS["samples.csv"],
    )
    log, _ = ingest.ingest(write=True)
    assert not log.has_errors, log.report()


def test_missing_control_produces_warning_not_error(scratch: Path):
    """対照が無いのは登録は通るが、WT 自動選択ができない旨を警告する。"""
    _write(
        scratch / "samples.csv",
        [
            ["S1", "GSE1", "M1", "KO", "mutant", "FALSE", "kidney", "", "", "", "", "", ""],
            ["S2", "GSE1", "M1", "KO", "mutant", "FALSE", "kidney", "", "", "", "", "", ""],
            ["S3", "GSE1", "M1", "KO", "mutant", "FALSE", "kidney", "", "", "", "", "", ""],
            ["S4", "GSE1", "M1", "KO", "mutant", "FALSE", "kidney", "", "", "", "", "", ""],
        ],
        HEADERS["samples.csv"],
    )
    log, _ = ingest.ingest(write=True)
    assert not log.has_errors, log.report()
    assert any("is_control=TRUE" in i.message for i in log.warnings)


def test_expression_column_not_in_samples_is_error(scratch: Path):
    _write(
        scratch / "expression" / "GSE1.csv",
        [["GeneA", 10, 12, 100, 110, 5]],
        ["gene_id", "S1", "S2", "S3", "S4", "S_GHOST"],
    )
    log, _ = ingest.ingest(write=True)
    assert any("S_GHOST" in i.message for i in log.errors)


def test_sample_missing_from_matrix_is_warning(scratch: Path):
    _write(
        scratch / "expression" / "GSE1.csv",
        [["GeneA", 10, 12, 100]],
        ["gene_id", "S1", "S2", "S3"],
    )
    log, _ = ingest.ingest(write=True)
    assert not log.has_errors, log.report()
    assert any("S4" in i.message for i in log.warnings)


def test_missing_expression_file_is_error(scratch: Path):
    (scratch / "expression" / "GSE1.csv").unlink()
    log, _ = ingest.ingest(write=True)
    assert any("発現マトリクス" in i.message for i in log.errors)


def test_negative_counts_flagged(scratch: Path):
    _write(
        scratch / "expression" / "GSE1.csv",
        [["GeneA", -5, 12, 100, 110]],
        ["gene_id", "S1", "S2", "S3", "S4"],
    )
    log, _ = ingest.ingest(write=True)
    assert any("負の値" in i.message for i in log.errors)


def test_duplicate_gene_ids_aggregated_by_policy(scratch: Path):
    """duplicate_policy=max で重複行が集約される。"""
    _write(
        scratch / "expression" / "GSE1.csv",
        [["GeneA", 10, 12, 100, 110], ["GeneA", 90, 92, 900, 910]],
        ["gene_id", "S1", "S2", "S3", "S4"],
    )
    log, _ = ingest.ingest(write=True)
    assert not log.has_errors, log.report()
    assert any("重複した gene_id" in i.message for i in log.warnings)

    store.reset_store()
    values = store.get_store().query(
        "SELECT value FROM expression WHERE gene_id = 'GeneA' AND sample_id = 'S1'"
    )
    assert values.iloc[0, 0] == pytest.approx(90.0)


def test_unknown_organ_is_warning_with_suggestion(scratch: Path):
    """語彙外の臓器名は警告どまりで、同義語なら正式名を提示する。"""
    import shutil

    repo_vocab = Path(__file__).resolve().parents[2] / "data" / "vocab"
    shutil.copytree(repo_vocab, scratch / "vocab")
    _write(
        scratch / "samples.csv",
        [
            ["S1", "GSE1", "M1", "WT", "WT", "TRUE", "renal", "", "", "", "", "", ""],
            ["S2", "GSE1", "M1", "WT", "WT", "TRUE", "renal", "", "", "", "", "", ""],
            ["S3", "GSE1", "M1", "KO", "mutant", "FALSE", "renal", "", "", "", "", "", ""],
            ["S4", "GSE1", "M1", "KO", "mutant", "FALSE", "renal", "", "", "", "", "", ""],
        ],
        HEADERS["samples.csv"],
    )
    log, _ = ingest.ingest(write=True)
    assert not log.has_errors, log.report()
    assert any("kidney" in i.message for i in log.warnings)


def test_unknown_columns_are_ignored_with_warning(scratch: Path):
    """作業メモ列を残したままでも登録できる。"""
    header = HEADERS["samples.csv"] + ["作業メモ"]
    _write(
        scratch / "samples.csv",
        [
            ["S1", "GSE1", "M1", "WT", "WT", "TRUE", "kidney", "", "", "", "", "", "", "確認済み"],
            ["S2", "GSE1", "M1", "WT", "WT", "TRUE", "kidney", "", "", "", "", "", "", ""],
            ["S3", "GSE1", "M1", "KO", "mutant", "FALSE", "kidney", "", "", "", "", "", "", ""],
            ["S4", "GSE1", "M1", "KO", "mutant", "FALSE", "kidney", "", "", "", "", "", "", ""],
        ],
        header,
    )
    log, _ = ingest.ingest(write=True)
    assert not log.has_errors, log.report()
    assert any("仕様外の列" in i.message for i in log.warnings)


def test_check_mode_does_not_write_build(scratch: Path):
    log, _ = ingest.ingest(write=False)
    assert not log.has_errors
    assert not config.manifest_path().exists()


def test_errors_prevent_partial_build(scratch: Path):
    """エラーがある状態で中途半端なストアを残さない。"""
    ingest.ingest(write=True)
    assert config.manifest_path().exists()
    first = config.manifest_path().read_text(encoding="utf-8")

    _write(
        scratch / "datasets.csv",
        [["GSE1", "研究1", "M_GONE", "Mus musculus", "RNA-seq", "counts", "symbol", "", "max", "", "", "", ""]],
        HEADERS["datasets.csv"],
    )
    log, _ = ingest.ingest(write=True)
    assert log.has_errors
    # manifest は更新されず、前回の内容が残る
    assert config.manifest_path().read_text(encoding="utf-8") == first


def test_header_only_templates_ingest_and_serve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """データ未登録（テンプレートのみ）でも ingest と API が動く。

    新規利用者が最初に踏む経路なので、空の状態で落ちないことを保証する。
    """
    import shutil

    from fastapi.testclient import TestClient

    from dmdeg.api.main import create_app

    data = tmp_path / "data"
    repo_data = Path(__file__).resolve().parents[2] / "data"
    data.mkdir()
    for name in ("models.csv", "datasets.csv", "samples.csv", "genes.csv", "comparisons.csv"):
        shutil.copy(repo_data / name, data / name)
    shutil.copytree(repo_data / "vocab", data / "vocab")

    monkeypatch.setenv("DMDEG_DATA_DIR", str(data))
    monkeypatch.setenv("DMDEG_BUILD_DIR", str(tmp_path / "build"))
    store.reset_store()

    log, manifest = ingest.ingest(write=True)
    assert not log.has_errors, log.report()
    assert manifest["counts"]["datasets"] == 0

    client = TestClient(create_app())
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/datasets").json() == []
    assert client.get("/api/models").json() == []
    assert client.get("/api/facets").json()["organs"] == []
    assert client.get("/api/genes/search", params={"q": "Actb"}).json() == []


def test_tsv_expression_file_accepted(scratch: Path):
    """GEO 由来でよくある tsv も拡張子候補として受理する。"""
    (scratch / "expression" / "GSE1.csv").unlink()
    path = scratch / "expression" / "GSE1.tsv"
    path.write_text("gene_id\tS1\tS2\tS3\tS4\nGeneA\t10\t12\t100\t110\n", encoding="utf-8")
    log, _ = ingest.ingest(write=True)
    assert not log.has_errors, log.report()
