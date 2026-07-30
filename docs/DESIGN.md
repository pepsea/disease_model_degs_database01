# 疾患モデル遺伝子発現データベース + 閲覧Website 設計書

## 1. 背景と目的

GEO 等から収集した疾患モデル動物の遺伝子発現データが、個々のファイルや解析スクリプトに散在している。その結果「このモデルのこの臓器で、この遺伝子は WT に比べてどう動くのか」を調べるたびに手作業のやり直しが発生している。

本システムが目指す状態は次の2点である。

1. キュレーターは **CSV を所定の場所に置くだけ** でデータを登録できる（SQL を書かない）。
2. 閲覧者は Web UI 上で「モデル種別 / GEO ID / 臓器 / 個別サンプル / 比較対象」を選び、発現全体像・遺伝子ごとの発現量・比較量・PCA を即座に得られる。

## 2. 要件

### 2.1 選択肢（入力）

| 選択軸 | 供給元 | 備考 |
|---|---|---|
| 動物モデルの種類 | `models.csv` | 疾患カテゴリ・改変様式でも絞り込み |
| 遺伝子発現データID (GEO) | `datasets.csv` | GSE 番号 |
| 臓器 | `samples.csv` の `organ` | 統制語彙で表記ゆれを抑制 |
| 個々のデータ | `samples.csv` の `sample_id` | GSM 単位でチェックボックス選択 |
| 比較対象データ | 比較ビルダー | 既定は同一データセット・同一臓器の WT。任意の他データにも差し替え可 |

### 2.2 出力

- **遺伝子発現全体像**: 高変動遺伝子ヒートマップ、サンプル間相関ヒートマップ、階層クラスタリング
- **遺伝子ごとの発現量**: 群別 box/violin/dot プロット、モデル横断のフォレストプロット
- **比較量**: log2 fold change、volcano プロット、MA プロット、DEG 表（閾値スライダ・CSV 出力）
- **多変量解析**: 主成分分析（PC 軸選択・色分け軸選択・寄与率スクリープロット）

### 2.3 「SQL ではなく CSV で登録」の解釈

**キュレーターが触るのは `data/` 配下の CSV のみ。** DDL 管理・マイグレーション・SQL 記述は一切発生しない。

内部の検索エンジンとしては DuckDB + Parquet を用いるが、これは `ingest` コマンドが CSV から自動生成する**再生成可能なビルド成果物**（`build/` は gitignore 対象）であり、登録インターフェースではない。`build/` を削除して再 ingest すれば完全に復元される。

この構成を選ぶ理由は、CSV を直接スキャンする方式では遺伝子1件の横断検索で全ファイルを読み直すことになり、データセット数の増加に対して閲覧応答性が破綻するためである。CSV を正、Parquet を派生とすることで、登録の簡便さと閲覧性能を両立する。

## 3. アーキテクチャ

```
data/*.csv  ──ingest──▶  build/parquet/ + build/dmdeg.duckdb
 (正・git管理)              (派生・gitignore)
                                  │
                                  ▼
                      FastAPI (dmdeg.api)  ── numpy/scipy/scikit-learn
                                  │              による正規化・統計・PCA
                                  ▼
                      React SPA (Vite + Plotly)
```

### 想定規模と実装形態

- 性能目標: 〜50 GSE / 〜2,000 サンプル。スキーマは大規模化を見込んだ設計とする。
- バックエンド: Python 3.11 + FastAPI。解析に numpy/scipy/scikit-learn を使えることを重視。
- フロントエンド: React + TypeScript + Plotly。URL 共有と多人数同時閲覧に耐えることを重視。
- UI 言語: 日本語。文言は `frontend/src/lib/i18n.ts` に集約し、将来の日英切替を阻害しない。
- 認証: 環境変数で有効化できる BASIC 認証相当のみ（既定は無効・内部利用前提）。

## 4. データモデル

CSV の詳細な列仕様は [`DATA_FORMAT.md`](./DATA_FORMAT.md) を参照。

```
data/
  models.csv                    # 疾患モデルのマスタ
  datasets.csv                  # GEO データセット（研究）単位のマスタ
  samples.csv                   # 個々のサンプル（GSM）とその属性
  genes.csv                     # 任意: 遺伝子アノテーション
  comparisons.csv               # 任意: 定義済み比較（既定の case vs control）
  expression/<dataset_id>.csv   # 発現マトリクス（1データセット1ファイル）
  degs/<comparison_id>.csv      # 任意: 外部解析済み DEG 結果表
  vocab/{organ,species,modality}.csv  # 統制語彙
```

### 4.1 テーブル間の関係

```
models (model_id)
  └─◀ datasets (dataset_id, model_id)
        ├─◀ samples (sample_id, dataset_id, model_id, organ, genotype, is_control)
        │     └─▶ expression/<dataset_id>.csv の列見出しと 1:1 対応
        └─◀ comparisons (comparison_id, dataset_id, case/control group_label)
              └─▶ degs/<comparison_id>.csv
```

### 4.2 発現マトリクスの形式

キュレーターは見慣れた**ワイド形式**（行 = 遺伝子、列 = サンプル）で登録する。ingest がロング形式 `(gene_id, sample_id, value)` に変換して Parquet に格納するため、閲覧側は遺伝子1件の取得で列選択を伴わず、データセット横断検索も同一クエリで処理できる。

重複 `gene_id` は `datasets.csv` の `duplicate_policy`（既定 `max`）に従って集約する。

### 4.3 二段構えの DEG 解析

| 経路 | 生成方法 | UI 上の位置づけ |
|---|---|---|
| オンザフライ統計 | システムが Welch t 検定 + BH 補正で即時計算 | **探索用**。任意の群組み合わせに対応 |
| 登録済み DEG 表 | DESeq2 / limma 等で外部作成し `degs/` に登録 | **厳密解析結果**。別タブで併置 |

両者を明示的に区別表示することで、探索の柔軟性と統計的厳密さを混同させない。

## 5. 内部ストア（自動生成・gitignore）

`python -m dmdeg.ingest` が冪等に再構築する。

- `build/parquet/expression/dataset_id=<GSE>/part.parquet` — ロング形式・`gene_id` ソート済み。行グループ統計により単一遺伝子の横断検索が高速。
- `build/parquet/{models,datasets,samples,genes,comparisons,degs}.parquet`
- `build/dmdeg.duckdb` — 上記 Parquet への VIEW 集合 + 遺伝子シンボル検索インデックス
- `build/manifest.json` — ソース CSV のハッシュ・ingest 時刻・件数・警告一覧（UI の収載状況ページで表示）

## 6. 取り込み時バリデーション

エラーは 1 件目で停止せず、**ファイル名・行番号付きでまとめて報告**する。

- 参照整合性: `samples.dataset_id` ∈ datasets、`samples.model_id` ∈ models、`comparisons` の group_label が実在
- 発現マトリクス列 ⊆ 当該 dataset の `sample_id`（過剰列はエラー、欠損列は警告として分離）
- `(dataset_id, organ)` ごとに `is_control=TRUE` が 1 件以上あるか（無ければ「既定比較が不能」の警告）
- 統制語彙外の `organ` / `species` / `modality` は警告 + 近似候補の提示（自由記述自体は許容）
- 数値列の型・負値・NaN 率チェック、`unit` と値域の整合性チェック

## 7. 解析ロジック

`backend/dmdeg/analysis/`

| モジュール | 内容 |
|---|---|
| `normalize.py` | `unit` に応じた CPM / TPM 換算、`log2(x+1)` 表示値、サンプル間中央値スケーリング。データセット横断表示時は各データセット内 z-score を既定にしてバッチ差を緩和 |
| `stats.py` | 群平均の log2FC、Welch t 検定、Benjamini-Hochberg FDR、効果量 |
| `pca.py` | 高変動遺伝子 top-N（既定 2000）→ log 変換 → 遺伝子ごと z-score → SVD。PC1〜PC5 の寄与率とサンプルローディング |
| `cluster.py` | サンプル間相関行列（Spearman / Pearson）、階層クラスタリングの並べ替え順序 |

**データセットをまたぐ比較はバッチ交絡の警告を必ずレスポンスに含め、UI にバナー表示する。** 異なる研究間の絶対発現量の直接比較は技術的交絡を含むため、既定ではデータセット内 z-score による相対比較を提示する。

## 8. API

カタログ系（ファセット選択肢の供給）

- `GET /api/models` / `GET /api/organs` / `GET /api/species`
- `GET /api/datasets?species=&model_id=&organ=&disease_category=&q=` → 件数付きファセット結果
- `GET /api/datasets/{dataset_id}` → メタデータ + サンプル一覧 + 利用可能な比較
- `GET /api/samples?dataset_id=&organ=&genotype=`
- `GET /api/genes/search?q=&species=` → 前方一致 + エイリアス解決

データ・解析系

- `GET /api/expression/gene?gene=&dataset_id=&organ=&group_by=` → 群別プロット用の生値 + 要約統計
- `POST /api/compare` → `{case: {sample_ids | {dataset_id, group_label}}, control: {...}, scope, method}`。**control 省略時は case と同一 dataset + organ の `is_control=TRUE` を自動採用**（=「主に WT」の既定挙動）
- `POST /api/analysis/pca` → `{sample_ids, n_top_genes, color_by}`
- `POST /api/analysis/heatmap` → 高変動遺伝子または指定遺伝子セットの行列
- `POST /api/analysis/correlation` → 相関行列 + クラスタ順序
- `GET /api/degs?comparison_id=` → 登録済み DEG 表
- `GET /api/export/*` → 表示中データの CSV ダウンロード
- `GET /api/status` → `manifest.json` 由来の収載状況・警告

## 9. 画面設計

**選択状態は全て URL クエリに反映**し、解析結果をそのままリンク共有できるようにする。
例: `?model=MDL_DB_DB&dataset=GSE12345&organ=kidney&genes=Havcr1,Lcn2&case=...&control=...`

| 画面 | 内容 |
|---|---|
| `/` ブラウズ | 左にファセット（モデル種別・疾患カテゴリ・種・臓器・アッセイ）、右にデータセット一覧カード。収載状況サマリ |
| `/datasets/:id` | データセット詳細。サンプル表（チェックボックスで個別選択）、群構成、PCA / 相関ヒートマップによる品質確認、高変動遺伝子ヒートマップ = **発現全体像** |
| `/genes/:symbol` | 遺伝子ごとの発現量。データセット × 臓器 × 群のドット / box プロット、モデル横断の log2FC フォレストプロット |
| `/compare` | **比較ビルダー**。case 群と control 群をそれぞれ「データセット → 臓器 → 群 または個別サンプル」で組み立てる。control は既定で WT が自動選択され、任意の他データに差し替え可。出力は volcano / MA / DEG 表。登録済み DEG 表がある比較は「厳密解析結果」タブとして併置 |
| `/analysis` | 任意サンプル集合での PCA、階層クラスタリング、相関ヒートマップ |
| `/docs` | CSV 登録手順・列仕様・バリデーションエラーの読み方 |

共通コンポーネント: `SelectionPanel`（横断的な選択状態）、`GroupBuilder`（case / control 構築）、`GeneAutocomplete`、`PlotCard`（凡例・ダウンロード・全画面化の共通化）。

## 10. リポジトリ構成

```
README.md  pyproject.toml  docker-compose.yml  .gitignore
data/                     # ← キュレーターが触る唯一の場所（CSV）
docs/{DESIGN.md,DATA_FORMAT.md}
backend/dmdeg/
  config.py schema.py ingest.py store.py
  analysis/{normalize,stats,pca,cluster}.py
  api/main.py  api/routers/{catalog,expression,compare,analysis,export}.py
  tests/
frontend/src/{App.tsx,api/,components/,charts/,pages/,lib/i18n.ts}
scripts/{make_example_data.py,ingest.sh}
build/                    # gitignore（Parquet + DuckDB + manifest）
```

依存: `fastapi uvicorn pandas pyarrow duckdb numpy scipy scikit-learn pydantic pytest httpx` / Node は Vite + React + TypeScript + Plotly + TanStack Query + Tailwind。

## 11. 実装マイルストーン

| # | 内容 |
|---|---|
| M1 | スキーマ & 取り込み: CSV 列仕様、`schema.py` バリデーション、`ingest.py`、`scripts/make_example_data.py`（2 GSE × 2 臓器 × WT / 疾患の合成データ） |
| M2 | クエリ層 & カタログ API: `store.py`、カタログ系エンドポイント、`/api/status` |
| M3 | フロント基盤: Vite セットアップ、ブラウズ画面、データセット詳細、URL 状態同期 |
| M4 | 遺伝子ビュー & 比較: `/api/expression/gene`、`/api/compare`、GroupBuilder、volcano / MA / DEG 表 |
| M5 | 全体像 & 多変量解析: PCA・ヒートマップ・相関 / クラスタリング、CSV エクスポート |
| M6 | 仕上げ: 任意 BASIC 認証、docker-compose、実データ 1 件の登録リハーサル |

## 12. 検証方法

- **単体テスト** (`pytest backend/dmdeg/tests`): `stats.py` の log2FC / Welch t / BH を scipy 直接計算と照合。`pca.py` の寄与率合計と既知データでの軸再現。`ingest.py` に壊れた CSV（参照切れ・列不一致・control 欠如）を与え、期待エラーが全件列挙されることを確認
- **エンドツーエンド**: `python scripts/make_example_data.py && python -m dmdeg.ingest` → `build/` 生成と `manifest.json` の件数を確認 → `uvicorn dmdeg.api.main:app` 起動 → `httpx` で各エンドポイントを叩き、合成データに埋め込んだ既知の差分遺伝子が `/api/compare` 上位に出ること・control 省略時に WT が自動選択されることを assert
- **UI スモーク**: Playwright で 6 画面を巡回し、グラフ描画・CSV ダウンロード・URL 復元（クエリ付き URL を直接開いて同じ結果になること）を確認
- **手動確認**: 実 GEO データ 1 件を `data/` に置いて ingest → `/compare` で WT 比較を実行し、元論文の報告と方向が一致するかを目視確認

## 13. 未確定事項

実装着手前に確認したい設計判断。現状は括弧内の方針を仮定している。

1. **実装形態**（FastAPI + React を仮定）— Streamlit / Dash 単体なら工数は大幅に減るが、URL 共有と多人数同時アクセスは弱くなる。完全静的サイト（DuckDB-WASM + GitHub Pages）ならサーバ管理不要で論文添付の公開 DB に向くが、大規模データと重い解析には不利。
2. **登録データのレベル**（発現マトリクス + 登録済み DEG 表の両方を仮定）— GEO からの自動ダウンロード機能を含めるかは将来拡張として保留。
3. **想定規模**（〜50 GSE / 〜2,000 サンプルを仮定）— 数万サンプル規模ならキャッシュ層と Parquet 分割戦略を M1 から設計に含める必要がある。
4. **UI 言語と公開範囲**（日本語 UI・内部利用を仮定）— 一般公開するなら英語化と i18n 対応を M6 に含める。
