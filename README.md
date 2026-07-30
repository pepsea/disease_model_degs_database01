# disease_model_degs_database01

疾患モデル動物の遺伝子発現データを蓄積し、Web 上で閲覧・比較解析するための仕組み。

**現状はまだ設計段階であり、アプリケーションコードは未実装。** 設計内容は以下を参照。

- [`docs/DESIGN.md`](docs/DESIGN.md) — システム設計書（アーキテクチャ、API、画面、解析ロジック、実装計画）
- [`docs/DATA_FORMAT.md`](docs/DATA_FORMAT.md) — CSV 登録フォーマット仕様と登録手順

## 何ができるようになるか

**選択できるもの**

- 動物モデルの種類（疾患カテゴリ・改変様式でも絞り込み）
- 遺伝子発現データ ID（GEO の GSE 番号）
- 臓器
- 個々のサンプル（GSM 単位）
- 比較対象データ（既定は同一データセット・同一臓器の WT。任意の他データにも差し替え可）

**得られるもの**

- 遺伝子発現の全体像（高変動遺伝子ヒートマップ、サンプル間相関、階層クラスタリング）
- 遺伝子ごとの発現量（群別プロット、モデル横断のフォレストプロット）
- 比較量（log2 fold change、volcano / MA プロット、DEG 表）
- 主成分分析（PC 軸選択・色分け軸選択・寄与率）

## データ登録の考え方

**登録作業は `data/` 配下に CSV を置くだけ。SQL は書かない。**

```
data/
  models.csv                    # 疾患モデルのマスタ
  datasets.csv                  # GEO データセット単位のマスタ
  samples.csv                   # 個々のサンプルとその属性
  genes.csv                     # 任意: 遺伝子アノテーション
  comparisons.csv               # 任意: 定義済み比較
  expression/<dataset_id>.csv   # 発現マトリクス（行=遺伝子, 列=サンプル）
  degs/<comparison_id>.csv      # 任意: 外部解析済み DEG 結果表
  vocab/                        # 統制語彙（表記ゆれ防止）
```

置いた後に取り込みコマンドを実行すると、検索用の内部ストア（`build/`、gitignore 対象）が再構築される。

```bash
python -m dmdeg.ingest --check   # 検証のみ
python -m dmdeg.ingest           # 検証 + ビルド
```

`build/` は CSV から機械的に再生成される派生物なので、削除しても CSV から完全に復元できる。**正となるデータは常に `data/` の CSV。**

列仕様と具体的な登録手順は [`docs/DATA_FORMAT.md`](docs/DATA_FORMAT.md) にまとめてある。

## 想定スタック

| 層 | 技術 |
|---|---|
| 登録 | CSV（git 管理） |
| 内部ストア | Parquet + DuckDB（自動生成・再生成可能） |
| バックエンド | Python 3.11 / FastAPI / numpy・scipy・scikit-learn |
| フロントエンド | React + TypeScript + Plotly + Vite |

## 未確定事項

実装着手前に確認したい設計判断が [`docs/DESIGN.md` の §13](docs/DESIGN.md#13-未確定事項) にある。特に実装形態（FastAPI + React / Streamlit 単体 / 完全静的サイト）は工数と運用性が大きく変わるため、着手前に決めたい。
