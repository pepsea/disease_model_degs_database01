/** データ登録方法と収載状況（取り込み時の警告の読み方）。 */

import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ErrorBox, PlotCard, Spinner, Tag } from "../components/common";

export function Docs() {
  const status = useQuery({ queryKey: ["status"], queryFn: api.status });

  const issues = status.data?.issues ?? [];
  const errors = issues.filter((issue) => issue.level === "error");
  const warnings = issues.filter((issue) => issue.level === "warning");

  return (
    <div className="content">
      <h1>データ登録方法</h1>

      <PlotCard title="登録の流れ" description="SQL は書きません。CSV を置いて取り込みコマンドを実行するだけです。">
        <ol className="steps">
          <li>
            <code>data/models.csv</code> に疾患モデルの行を追記します（既存モデルなら不要）。
          </li>
          <li>
            <code>data/datasets.csv</code> に GEO データセットの行を追記します。
            <strong>
              <code>unit</code>（counts / tpm / fpkm / log2_intensity）は正規化処理の分岐に使うため、正確に指定してください。
            </strong>
          </li>
          <li>
            <code>data/samples.csv</code> にサンプル行を追記します。
            <strong>
              対照サンプルに <code>is_control=TRUE</code> を付けてください。
            </strong>
            これが「比較対象に WT を自動選択」の判定に使われます。
          </li>
          <li>
            <code>data/expression/&lt;dataset_id&gt;.csv</code> に発現マトリクスを置きます。1 列目が
            <code>gene_id</code>、2 列目以降がサンプル列で、列見出しは <code>sample_id</code> と一致させます。
          </li>
          <li>
            検証してから取り込みます。
            <pre>
              <code>
                python -m dmdeg.ingest --check{"\n"}python -m dmdeg.ingest
              </code>
            </pre>
          </li>
        </ol>
        <p className="muted">
          列仕様の詳細はリポジトリの <code>docs/DATA_FORMAT.md</code> にあります。DESeq2 等の解析結果は
          <code>data/comparisons.csv</code> と <code>data/degs/&lt;comparison_id&gt;.csv</code> に登録すると、
          比較画面の「厳密解析結果」タブに表示されます。
        </p>
      </PlotCard>

      <PlotCard title="エラーと警告の違い">
        <table className="table">
          <thead>
            <tr>
              <th>種別</th>
              <th>扱い</th>
              <th>例</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <Tag tone="case">エラー</Tag>
              </td>
              <td>取り込みを中断します。既存のデータは書き換わりません。</td>
              <td>
                参照先の存在しない <code>dataset_id</code>、未定義の <code>unit</code>、
                <code>samples.csv</code> に無いサンプル列、counts に負の値
              </td>
            </tr>
            <tr>
              <td>
                <Tag tone="control">警告</Tag>
              </td>
              <td>取り込みは成功します。内容の確認を促すものです。</td>
              <td>
                語彙にない臓器名、対照サンプルの不在、発現マトリクスに列が無いサンプル、仕様外の列、
                重複した <code>gene_id</code>
              </td>
            </tr>
          </tbody>
        </table>
        <p className="muted">
          エラーは 1 件目で止まらず、ファイル名・行番号・列名を付けてまとめて出力されます。一度の実行で全部
          直せるようにするためです。
        </p>
      </PlotCard>

      <PlotCard title="現在の収載状況">
        {status.isPending ? <Spinner /> : null}
        {status.error ? <ErrorBox error={status.error} /> : null}
        {status.data ? (
          <>
            {status.data.generated_at ? (
              <p>
                最終取り込み: {new Date(status.data.generated_at).toLocaleString("ja-JP")}
              </p>
            ) : (
              <p className="muted">{status.data.message ?? "まだ取り込みが実行されていません。"}</p>
            )}
            <dl className="stats">
              {Object.entries(status.data.counts).map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>

            {Object.keys(status.data.datasets ?? {}).length > 0 ? (
              <table className="table">
                <thead>
                  <tr>
                    <th>データセット</th>
                    <th>遺伝子数</th>
                    <th>サンプル数</th>
                    <th>取り込み元ファイル</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(status.data.datasets).map(([id, info]) => (
                    <tr key={id}>
                      <td>{id}</td>
                      <td className="num">{info.n_genes}</td>
                      <td className="num">{info.n_samples}</td>
                      <td>
                        <code>{info.source_file}</code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}

            {errors.length > 0 || warnings.length > 0 ? (
              <>
                <h3>
                  取り込み時のエラー {errors.length} 件 / 警告 {warnings.length} 件
                </h3>
                <div className="table-scroll">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>種別</th>
                        <th>ファイル</th>
                        <th>行</th>
                        <th>列</th>
                        <th>内容</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...errors, ...warnings].map((issue, index) => (
                        <tr key={index}>
                          <td>
                            {issue.level === "error" ? (
                              <Tag tone="case">エラー</Tag>
                            ) : (
                              <Tag tone="control">警告</Tag>
                            )}
                          </td>
                          <td>
                            <code>{issue.file}</code>
                          </td>
                          <td className="num">{issue.row ?? "—"}</td>
                          <td>{issue.column ?? "—"}</td>
                          <td>{issue.message}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <p className="muted">取り込み時の問題はありません。</p>
            )}
          </>
        ) : null}
      </PlotCard>

      <PlotCard title="数値の扱い">
        <ul className="list">
          <li>
            <strong>正規化</strong>: <code>unit=counts</code> のデータのみ CPM 換算します。
            <code>tpm</code> / <code>fpkm</code> / <code>log2_intensity</code> は登録値をそのまま使います
            （log2_intensity を二重に log 変換しません）。
          </li>
          <li>
            <strong>log2FC</strong>: 正規化後の線形値の群平均比（擬似カウント +1）。
          </li>
          <li>
            <strong>検定</strong>: log2 変換後の値に Welch の t 検定または Mann-Whitney U 検定を行い、
            Benjamini-Hochberg 法で FDR 補正します。反復が 2 未満の群では検定せず log2FC のみ返します。
          </li>
          <li>
            <strong>探索用と厳密解析の区別</strong>: サイト上の統計は分散の事前分布モデルを持たないため探索用です。
            確定的な DEG 判定には DESeq2 / limma の結果を <code>data/degs/</code> に登録してください。
          </li>
          <li>
            <strong>研究間比較</strong>: データセットをまたぐ比較にはバッチ交絡の警告が必ず付きます。
            横断表示ではデータセット内 z-score を使うと技術的差異の影響を抑えられます。
          </li>
        </ul>
      </PlotCard>
    </div>
  );
}
