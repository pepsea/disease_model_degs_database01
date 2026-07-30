"""テスト用の一時データディレクトリと ingest 済みストア。

本物の `data/` を触らないよう、合成データを tmp に生成してから
環境変数でそこを指す。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import make_example_data  # noqa: E402  (sys.path 追加後にインポートする必要がある)


@pytest.fixture(scope="session")
def example_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """合成データを生成して ingest まで済ませた作業ディレクトリを返す。"""
    root = tmp_path_factory.mktemp("dmdeg")
    data = root / "data"
    build = root / "build"

    # 生成スクリプトが統制語彙も複製するので、ここでは出力先を渡すだけでよい
    make_example_data.main(["--out", str(data), "--force"])

    import os

    os.environ["DMDEG_DATA_DIR"] = str(data)
    os.environ["DMDEG_BUILD_DIR"] = str(build)

    from dmdeg import ingest, store

    store.reset_store()
    log, _ = ingest.ingest(write=True)
    assert not log.has_errors, log.report()
    return root


@pytest.fixture()
def store(example_root: Path):
    from dmdeg import store as store_module

    store_module.reset_store()
    return store_module.get_store()


@pytest.fixture()
def client(example_root: Path):
    from fastapi.testclient import TestClient

    from dmdeg import store as store_module
    from dmdeg.api.main import create_app

    store_module.reset_store()
    return TestClient(create_app())


@pytest.fixture()
def spiked_kidney() -> dict[str, list[str]]:
    """GSE900001 腎で意図的に差を入れた遺伝子。"""
    return make_example_data.SPIKES[("GSE900001", "kidney")]
