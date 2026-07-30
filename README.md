# disease_model_degs_database01

疾患モデル動物の遺伝子発現データを蓄積し、Web 上で閲覧・比較解析する仕組み。

**データ登録は `data/` 配下の CSV のみ。SQL は書きません。**

- 設計の背景と判断: [`docs/DESIGN.md`](docs/DESIGN.md)
- CSV の列仕様と登録手順: [`docs/DATA_FORMAT.md`](docs/DATA_FORMAT.md)

---

## ローカルで動かす

### 必要なもの

- Python 3.11 以上
- Node.js 20 以上（Web UI をビルドする場合）

### Docker で起動する（Python も Node.js も入れずに済む）

Docker Desktop（または Docker Engine）だけあれば動きます。

```bash
git clone https://github.com/pepsea/disease_model_degs_database01.git
cd disease_model_degs_database01

# まず付属の合成データで動かす
docker compose --profile example up --build

# 自分のデータ（data/ 配下の CSV）で動かす
docker compose up --build
```

ブラウザで **http://127.0.0.1:8000** を開きます。初回のビルドは 3〜5 分かかります。

| 操作 | コマンド |
|---|---|
| 停止 | `docker compose down` |
| CSV を編集して反映 | `docker compose restart`（起動のたびに取り込み直します） |
| ログを見る | `docker compose logs -f` |
| ポートを変える | `docker compose up` の前に `docker-compose.yml` の `8000:8000` を編集 |
| BASIC 認証をかける | `DMDEG_BASIC_AUTH=user:pass docker compose up` |

**CSV に問題があるとサーバは起動しません。** 取り込みに失敗した時点でコンテナが終了し、
ファイル名・行番号付きのエラーがログに出ます。検証に失敗したまま古いデータを配信して
登録内容を偽って見せることがないようにしています。エラーを直して `docker compose up`
を再実行してください。

`data/` は読み取り専用でマウントされ、取り込み結果は Docker の名前付きボリュームに
入ります。ホスト側に `build/` は作られません。

### 一番簡単な起動方法（Docker を使わない場合）

起動スクリプトが、仮想環境の作成・依存関係の導入・CSV の取り込み・画面のビルド・
サーバ起動までまとめて行います。2 回目以降は既にあるものを再利用するので即座に起動します。

```bash
git clone https://github.com/pepsea/disease_model_degs_database01.git
cd disease_model_degs_database01

# macOS / Linux
./scripts/run_local.sh --example     # まず付属の合成データで動かす
./scripts/run_local.sh               # data/ に登録した自分のデータで動かす
```

```powershell
# Windows PowerShell
.\scripts\run_local.ps1 -Example
.\scripts\run_local.ps1
```

終了すると次のように表示されるので、ブラウザで開きます。

```
------------------------------------------------------------
 Web 画面: http://127.0.0.1:8000
 API 仕様: http://127.0.0.1:8000/api/docs
 終了するには Ctrl+C
------------------------------------------------------------
```

主なオプション（両スクリプト共通、PowerShell 版は `-Example` のように `-` 始まり）:

| オプション | 意味 |
|---|---|
| `--example` | `data/` ではなく付属の合成データを使う |
| `--port 9000` | ポートを変える（既定 8000） |
| `--rebuild` | 画面のビルドをやり直す |
| `--api-only` | Node.js を使わず API のみ起動する |

初回のみ、依存関係の導入と画面のビルドで合計 3〜5 分かかります。

以下は、スクリプトが内部で行っていることを手動で実行する場合の手順です。

### 1. セットアップ（手動の場合）

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 2. まず合成データで動かしてみる

実データを用意する前に、付属の合成データで全機能を確認できます。**合成データは
`example_data/` にあり、実データの登録先 `data/` とは分けてあります。**

```bash
# 合成データを（必要なら）生成し、検索用ストアを構築する
python scripts/make_example_data.py --force
DMDEG_DATA_DIR=example_data DMDEG_BUILD_DIR=build_example python -m dmdeg.ingest

# Web UI をビルド
cd frontend && npm install && npm run build && cd ..

# 起動（API と UI を同じサーバから配信）
DMDEG_DATA_DIR=example_data DMDEG_BUILD_DIR=build_example \
  python -m uvicorn dmdeg.api.main:app --port 8000
```

ブラウザで **http://127.0.0.1:8000** を開きます。

Windows の PowerShell で環境変数を渡す場合:

```powershell
$env:DMDEG_DATA_DIR="example_data"; $env:DMDEG_BUILD_DIR="build_example"
python -m uvicorn dmdeg.api.main:app --port 8000
```

### 3. 自分のデータで動かす

```bash
# data/ 配下の CSV を編集したら、まず検証だけ実行する
python -m dmdeg.ingest --check

# 問題がなければストアを構築する
python -m dmdeg.ingest

# 起動（環境変数は不要。既定で data/ と build/ を使う）
python -m uvicorn dmdeg.api.main:app --port 8000
```

置くファイルと列は [`docs/DATA_FORMAT.md`](docs/DATA_FORMAT.md) にまとめてあります。
最小構成は `models.csv` / `datasets.csv` / `samples.csv` / `expression/<dataset_id>.csv` の 4 つです。

### UI を書き換えながら開発する場合

Vite の開発サーバを使うと即時反映されます（`/api` は 8000 番に転送されます）。

```bash
# 端末 1
python -m uvicorn dmdeg.api.main:app --port 8000 --reload
# 端末 2
cd frontend && npm run dev      # http://127.0.0.1:5173
```

### 環境変数

| 変数 | 既定値 | 用途 |
|---|---|---|
| `DMDEG_DATA_DIR` | `./data` | 登録元 CSV の場所 |
| `DMDEG_BUILD_DIR` | `./build` | 検索用ストアの出力先 |
| `DMDEG_BASIC_AUTH` | なし | `user:pass` を設定すると全エンドポイントに BASIC 認証をかける |
| `DMDEG_CORS_ORIGINS` | Vite 開発サーバ | 許可するオリジン（カンマ区切り） |

### テスト

```bash
pytest                                    # バックエンド（83 件）
cd frontend && npm run typecheck          # 型検査
cd frontend && npm run smoke              # 全画面のブラウザスモークテスト（要: 起動中の API）
```

`npm run smoke` は Playwright を使います。ブラウザが無い場合は
`npx playwright install chromium` を実行してください。

---

## 何ができるか

**選択できるもの**

- 動物モデルの種類（疾患カテゴリ・改変様式でも絞り込み）
- 遺伝子発現データ ID（GEO の GSE 番号）
- 臓器
- 個々のサンプル（GSM 単位のチェックボックス）
- 比較対象データ — 既定は同一データセット・同一臓器の WT が自動選択され、任意の他データにも差し替え可

**得られるもの**

| 画面 | 内容 |
|---|---|
| データセット | ファセット絞り込み、収載状況 |
| データセット詳細 | 群構成、サンプル表、高変動遺伝子ヒートマップ（発現全体像）、PCA、サンプル間相関 |
| 遺伝子 | 群別の発現量プロット、要約統計、モデル横断の WT 比フォレストプロット |
| 比較 | 比較ビルダー、Volcano / MA プロット、DEG 表、登録済み DEG 表（別タブ） |
| 解析 | PCA（軸・色分け選択、寄与率）、階層クラスタリング、相関、ヒートマップ |
| データ登録 | CSV の登録手順、取り込み時のエラー / 警告一覧 |

画面の選択状態はすべて URL クエリに入るので、解析結果をそのままリンクで共有できます。

---

## データの流れ

```
data/*.csv  ──ingest──▶  build/parquet/ + build/dmdeg.duckdb  ──▶  FastAPI  ──▶  React
 (正・git管理)              (派生・gitignore・再生成可能)
```

内部では DuckDB + Parquet を検索エンジンとして使いますが、これは `ingest` が CSV から
生成する派生物です。`build/` を消しても再実行で完全に復元されるので、**正となるデータは
常に `data/` の CSV** です。

CSV を直接スキャンする方式にしなかったのは、遺伝子 1 件の横断検索で全ファイルを
読み直すことになり、データセット数の増加で閲覧応答性が破綻するためです。

## 数値の扱いで意識している点

- **正規化**: `unit=counts` のみ CPM 換算。`tpm` / `fpkm` / `log2_intensity` は登録値のまま使い、
  マイクロアレイの log 値を二重に log 変換しません。
- **log2FC と検定の分離**: log2FC は正規化後の線形値の群平均比、検定は log2 変換後の値に対して
  Welch の t 検定（または Mann-Whitney U）＋ BH 補正。反復が 2 未満の群では検定せず log2FC のみ返します。
- **探索用と厳密解析の区別**: サイト上の統計は分散の事前分布モデルを持たないため探索用です。
  確定的な DEG 判定は DESeq2 / limma の結果を `data/degs/` に登録し、別タブで併置します。
- **研究間比較の注意喚起**: データセットをまたぐ比較・単位の混在・臓器の不一致・反復不足には、
  応答に必ず警告を付けて画面に表示します。黙って数値だけ返しません。
- **バッチ差の緩和**: 横断解析では「データセット内 z-score」を有効にできます。付属の合成データでは、
  これを有効にすると PC1 の寄与率が 74.6% → 13.8% に下がり、データセット間の分離が消えて
  臓器差だけが残ります。

## 想定スタック

| 層 | 技術 |
|---|---|
| 登録 | CSV（git 管理） |
| 内部ストア | Parquet + DuckDB（自動生成・再生成可能） |
| バックエンド | Python 3.11 / FastAPI / numpy・scipy |
| フロントエンド | React + TypeScript + Plotly + Vite |

API 仕様は起動後 http://127.0.0.1:8000/api/docs で確認できます。
