# データ登録フォーマット仕様

登録作業は **`data/` 配下に CSV を置くこと** だけで完結する。SQL を書く必要はない。

置いた後に次を実行すると、内部の検索用ストア（`build/`）が再構築される。

```bash
python -m dmdeg.ingest          # 検証 + ビルド
python -m dmdeg.ingest --check  # 検証のみ（ビルドしない）
```

検証エラーは 1 件目で止まらず、ファイル名・行番号付きでまとめて出力される。

## 共通ルール

- 文字コードは **UTF-8**（BOM 可）。改行は LF / CRLF どちらでも可。
- ヘッダ行は必須。列の順序は自由で、**列名で解釈する**。
- 仕様外の列は無視されるため、作業用メモ列を残したままでも登録できる。
- 真偽値は `TRUE` / `FALSE`（大小文字不問。`1` / `0`、`yes` / `no` も受理）。
- 空欄は欠損として扱う。必須列（●）が空欄の行はエラー。
- ID 列（`model_id` / `dataset_id` / `sample_id` / `comparison_id`）は前後の空白を除去して比較する。

---

## `data/models.csv` — 疾患モデルのマスタ

| 列名 | 必須 | 説明 |
|---|:--:|---|
| `model_id` | ● | 一意キー。英数字とアンダースコア（例 `MDL_DB_DB`） |
| `model_name` | ● | 表示名（例 `db/db マウス`） |
| `species` | ● | 学名（例 `Mus musculus`）。`vocab/species.csv` と照合 |
| `strain` | | 系統（例 `C57BLKS/J`） |
| `modality` | ● | `KO` / `KI` / `Tg` / `chemical` / `diet` / `surgical` / `spontaneous` |
| `target_gene` | | 遺伝子改変モデルの対象遺伝子（例 `Lepr`） |
| `disease_category` | ● | ファセット用の疾患分類（例 `代謝`, `腎`, `神経`） |
| `description` | | モデルの説明 |
| `reference_url` | | 参考文献・系統情報の URL |

## `data/datasets.csv` — GEO データセットのマスタ

| 列名 | 必須 | 説明 |
|---|:--:|---|
| `dataset_id` | ● | GSE 番号（例 `GSE123456`）。一意キー |
| `title` | ● | データセットのタイトル |
| `model_id` | ● | `models.csv` の `model_id` を参照 |
| `species` | ● | 学名 |
| `assay` | ● | `RNA-seq` / `microarray` / `scRNA-seq` |
| `unit` | ● | 発現値の単位。`counts` / `tpm` / `fpkm` / `log2_intensity`。**正規化処理の分岐に使うため必ず正確に指定する** |
| `gene_id_type` | ● | 発現マトリクスの `gene_id` の種類。`symbol` / `ensembl` / `entrez` |
| `platform` | | プラットフォーム（例 `GPL24247`, `Illumina NovaSeq 6000`） |
| `duplicate_policy` | | 重複 `gene_id` の集約方法。`max`（既定） / `sum` / `mean` / `first` |
| `pmid` | | 論文の PubMed ID |
| `geo_url` | | GEO のページ URL |
| `submitted_by` | | 登録者 |
| `notes` | | 備考。前処理の経緯などを残す |

> `unit` が `counts` の場合はシステム側で CPM / TPM 換算を行う。既に正規化済みの値を `counts` と申告すると二重正規化になるため注意。

## `data/samples.csv` — 個々のサンプル

| 列名 | 必須 | 説明 |
|---|:--:|---|
| `sample_id` | ● | GSM 番号（例 `GSM1234567`）。一意キー。**発現マトリクスの列見出しと一致させる** |
| `dataset_id` | ● | `datasets.csv` を参照 |
| `model_id` | ● | `models.csv` を参照。WT サンプルも所属モデルを指定する |
| `group_label` | ● | 実験群のラベル（例 `db/db_12w`, `WT_12w`）。比較の単位になる |
| `genotype` | ● | `WT` / `mutant` / `heterozygous` など |
| `is_control` | ● | `TRUE` なら既定の比較対象（対照群）。**同一 `dataset_id` × `organ` に 1 件以上必要** |
| `organ` | ● | 臓器（例 `kidney`, `liver`）。`vocab/organ.csv` と照合 |
| `tissue_detail` | | 部位の詳細（例 `renal cortex`） |
| `sex` | | `male` / `female` / `unknown` |
| `age_weeks` | | 週齢（数値） |
| `treatment` | | 処置（例 `vehicle`, `STZ 50mg/kg`） |
| `replicate` | | 反復番号 |
| `batch` | | バッチ識別子。PCA の色分け軸や交絡確認に使う |

## `data/expression/<dataset_id>.csv` — 発現マトリクス

ファイル名は `datasets.csv` の `dataset_id` と一致させる（例 `data/expression/GSE123456.csv`）。

- 1 列目: `gene_id`（`datasets.csv` の `gene_id_type` に従う）
- 2 列目以降: サンプル列。**ヘッダは `samples.csv` の `sample_id` と一致させる**

```csv
gene_id,GSM1234567,GSM1234568,GSM1234569,GSM1234570
Havcr1,12,15,842,910
Lcn2,45,38,1203,1150
Actb,15200,14980,15310,15005
```

- 行 = 遺伝子、列 = サンプルのワイド形式で登録する（内部でロング形式に変換される）
- 重複した `gene_id` は `duplicate_policy` に従って集約される
- `samples.csv` に無いサンプル列はエラー。逆に `samples.csv` にあってマトリクスに無いサンプルは警告

## `data/comparisons.csv` — 定義済み比較（任意）

よく使う比較に固定 ID を与え、外部解析済みの DEG 表を紐づけるための表。

| 列名 | 必須 | 説明 |
|---|:--:|---|
| `comparison_id` | ● | 一意キー（例 `CMP_GSE123456_KIDNEY_DBDB`） |
| `dataset_id` | ● | `datasets.csv` を参照 |
| `case_group_label` | ● | case 側の `group_label` |
| `control_group_label` | ● | control 側の `group_label` |
| `organ` | | 比較対象の臓器 |
| `method` | | `DESeq2` / `limma` / `edgeR` など |
| `label` | | UI 表示名（例 `db/db vs WT（腎, 12週）`） |

## `data/degs/<comparison_id>.csv` — 外部解析済み DEG 表（任意）

DESeq2 / limma / edgeR 等で作成した結果を登録する。ファイル名は `comparisons.csv` の `comparison_id` と一致させる。

| 列名 | 必須 | 説明 |
|---|:--:|---|
| `gene_id` | ● | `datasets.csv` の `gene_id_type` に従う |
| `log2fc` | ● | log2 fold change（case / control） |
| `pvalue` | | 生の p 値 |
| `padj` | | 多重比較補正後の p 値（FDR） |
| `base_mean` | | 平均発現量（MA プロット用） |

> ここに登録した結果は UI 上で「厳密解析結果」として表示される。システムが即時計算する Welch t 検定の結果とは別タブで併置され、混同されない。

## `data/vocab/*.csv` — 統制語彙

表記ゆれを抑えるための語彙表。**語彙外の値もエラーにはならず、警告 + 近似候補の提示にとどまる。**

- `vocab/organ.csv`: `term`, `label_ja`, `synonyms`（`;` 区切り）
- `vocab/species.csv`: `term`, `label_ja`, `common_name`, `synonyms`
- `vocab/modality.csv`: `term`, `label_ja`, `description`

---

## 登録手順の例

新しい GEO データセット `GSE999999`（アルポート症候群モデル、腎）を追加する場合。

1. `data/models.csv` にモデル行を追記（既存モデルなら不要）
   ```csv
   MDL_COL4A3_KO,Col4a3 KO マウス,Mus musculus,C57BL/6J,KO,Col4a3,腎,アルポート症候群モデル,
   ```
2. `data/datasets.csv` に 1 行追記
   ```csv
   GSE999999,Col4a3 KO kidney RNA-seq,MDL_COL4A3_KO,Mus musculus,RNA-seq,counts,symbol,GPL24247,max,,,taiga,
   ```
3. `data/samples.csv` にサンプル行を追記。**WT 側に `is_control=TRUE` を付ける**
4. `data/expression/GSE999999.csv` に発現マトリクスを配置
5. 検証してからビルド
   ```bash
   python -m dmdeg.ingest --check   # まず警告・エラーを確認
   python -m dmdeg.ingest           # 問題なければビルド
   ```
6. Web UI の収載状況ページで件数と警告を確認

必要なら DESeq2 等の結果を `data/comparisons.csv` + `data/degs/<comparison_id>.csv` として追加登録する。
