/** 比較画面: 比較ビルダー + volcano / MA / DEG 表。

登録済み DEG 表（外部の DESeq2 等）とオンザフライ統計は別タブに分ける。
探索用の数値と確定的な解析結果を同じ表に混ぜないため。
*/

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, downloadCsv, type CompareRow, type SampleSelection } from "../api/client";
import { Plot } from "../charts/Plot";
import { Empty, ErrorBox, Field, PlotCard, Spinner, Tag, Warnings, formatNumber } from "../components/common";
import { GroupBuilder } from "../components/GroupBuilder";
import { useUrlState } from "../lib/useUrlState";

type Tab = "onthefly" | "registered";

export function Compare() {
  const url = useUrlState();
  const [tab, setTab] = useState<Tab>("onthefly");

  const autoControl = url.getBool("auto", true);
  const method = url.get("method", "welch");
  const log2fcThreshold = url.getNumber("lfc", 1);
  const padjThreshold = url.getNumber("padj", 0.05);
  const comparisonId = url.get("comparison");

  const caseSelection: SampleSelection = {
    dataset_id: url.get("case_dataset") || null,
    organ: url.get("case_organ") || null,
    group_label: url.get("case_group") || null,
    sample_ids: url.getList("case_samples").length ? url.getList("case_samples") : null,
  };
  const controlSelection: SampleSelection = {
    dataset_id: url.get("ctrl_dataset") || null,
    organ: url.get("ctrl_organ") || null,
    group_label: url.get("ctrl_group") || null,
    sample_ids: url.getList("ctrl_samples").length ? url.getList("ctrl_samples") : null,
  };

  const datasets = useQuery({ queryKey: ["datasets", {}], queryFn: () => api.datasets({}) });

  const caseReady = Boolean(caseSelection.dataset_id || caseSelection.sample_ids?.length);

  const compare = useQuery({
    queryKey: ["compare", caseSelection, controlSelection, autoControl, method, log2fcThreshold, padjThreshold],
    queryFn: () =>
      api.compare({
        case: caseSelection,
        control: autoControl ? null : controlSelection,
        method,
        log2fc_threshold: log2fcThreshold,
        padj_threshold: padjThreshold,
        limit: 5000,
      }),
    enabled: caseReady,
  });

  const rows = compare.data?.rows ?? [];

  // volcano は 3 系列（有意な上昇 / 有意な下降 / それ以外）に分ける
  const volcano = useMemo(() => {
    if (!rows.length) return [];
    const buckets: Record<string, CompareRow[]> = { up: [], down: [], flat: [] };
    for (const row of rows) {
      const significant = row.padj !== null && row.padj <= padjThreshold;
      if (significant && row.log2fc >= log2fcThreshold) buckets.up.push(row);
      else if (significant && row.log2fc <= -log2fcThreshold) buckets.down.push(row);
      else buckets.flat.push(row);
    }
    const trace = (name: string, items: CompareRow[], color: string) => ({
      type: "scattergl",
      mode: "markers",
      name,
      x: items.map((row) => row.log2fc),
      y: items.map((row) => (row.padj && row.padj > 0 ? -Math.log10(row.padj) : 0)),
      text: items.map((row) => row.symbol),
      hovertemplate: "%{text}<br>log2FC %{x:.2f}<br>-log10(padj) %{y:.2f}<extra></extra>",
      marker: { size: name === "変化なし" ? 4 : 7, color, opacity: name === "変化なし" ? 0.35 : 0.85 },
    });
    return [
      trace("変化なし", buckets.flat, "#9aa5b1"),
      trace("上昇", buckets.up, "#e2725b"),
      trace("下降", buckets.down, "#5b8def"),
    ];
  }, [rows, log2fcThreshold, padjThreshold]);

  const maPlot = useMemo(() => {
    if (!rows.length) return [];
    return [
      {
        type: "scattergl",
        mode: "markers",
        x: rows.map((row) => Math.log2(row.base_mean + 1)),
        y: rows.map((row) => row.log2fc),
        text: rows.map((row) => row.symbol),
        hovertemplate: "%{text}<br>log2 平均発現 %{x:.2f}<br>log2FC %{y:.2f}<extra></extra>",
        marker: {
          size: 5,
          opacity: 0.6,
          color: rows.map((row) =>
            row.padj !== null && row.padj <= padjThreshold ? (row.log2fc > 0 ? "#e2725b" : "#5b8def") : "#9aa5b1",
          ),
        },
      },
    ];
  }, [rows, padjThreshold]);

  const summary = compare.data?.summary;

  return (
    <div className="content content--wide">
      <h1>比較</h1>

      <PlotCard
        title="比較ビルダー"
        description="case を指定すると、比較対象は同じデータセット・同じ臓器の対照（WT）が自動で選ばれます。任意の他データに差し替えることもできます。"
      >
        <GroupBuilder
          title="case（疾患・処置側）"
          datasets={datasets.data ?? []}
          value={caseSelection}
          onChange={(next) =>
            url.patch({
              case_dataset: next.dataset_id ?? "",
              case_organ: next.organ ?? "",
              case_group: next.group_label ?? "",
              case_samples: next.sample_ids ?? [],
            })
          }
        />

        <label className="checkbox">
          <input
            type="checkbox"
            checked={autoControl}
            onChange={(event) => url.patch({ auto: event.target.checked ? "1" : "0" })}
          />
          比較対象に WT を自動選択する（既定）
        </label>

        <GroupBuilder
          title="control（比較対象）"
          datasets={datasets.data ?? []}
          value={controlSelection}
          disabled={autoControl}
          onChange={(next) =>
            url.patch({
              ctrl_dataset: next.dataset_id ?? "",
              ctrl_organ: next.organ ?? "",
              ctrl_group: next.group_label ?? "",
              ctrl_samples: next.sample_ids ?? [],
            })
          }
        />

        <div className="builder__row">
          <Field label="検定方法">
            <select value={method} onChange={(event) => url.patch({ method: event.target.value })}>
              <option value="welch">Welch の t 検定</option>
              <option value="mannwhitney">Mann-Whitney U 検定</option>
            </select>
          </Field>
          <Field label={`|log2FC| 閾値: ${log2fcThreshold}`}>
            <input
              type="range"
              min={0}
              max={5}
              step={0.25}
              value={log2fcThreshold}
              onChange={(event) => url.patch({ lfc: event.target.value })}
            />
          </Field>
          <Field label={`FDR 閾値: ${padjThreshold}`}>
            <input
              type="range"
              min={0.01}
              max={0.5}
              step={0.01}
              value={padjThreshold}
              onChange={(event) => url.patch({ padj: event.target.value })}
            />
          </Field>
        </div>
      </PlotCard>

      {!caseReady ? <Empty>case 側のデータセットと群を選んでください。</Empty> : null}
      {compare.isPending && caseReady ? <Spinner label="比較を計算中…" /> : null}
      {compare.error ? <ErrorBox error={compare.error} /> : null}

      {compare.data ? (
        <>
          <Warnings items={compare.data.warnings} />

          <div className="summary-bar">
            <div>
              <span className="summary-bar__label">case</span>
              <strong>{compare.data.case_samples.length}</strong> 件
              <span className="muted">
                {" "}
                {Array.from(new Set(compare.data.case_samples.map((s) => s.group_label))).join(", ")}
              </span>
            </div>
            <div>
              <span className="summary-bar__label">control</span>
              <strong>{compare.data.control_samples.length}</strong> 件
              <span className="muted">
                {" "}
                {Array.from(new Set(compare.data.control_samples.map((s) => s.group_label))).join(", ")}
              </span>
              {compare.data.control_auto_selected ? <Tag tone="control">WT 自動選択</Tag> : null}
            </div>
            <div>
              <span className="summary-bar__label">有意</span>
              上昇 <strong>{summary?.n_up ?? 0}</strong> / 下降 <strong>{summary?.n_down ?? 0}</strong>
              <span className="muted"> （検定 {summary?.n_tested ?? 0} 遺伝子）</span>
            </div>
            <button
              type="button"
              onClick={() =>
                void downloadCsv("/export/compare", "compare.csv", {
                  method: "POST",
                  body: {
                    case: caseSelection,
                    control: autoControl ? null : controlSelection,
                    method,
                    log2fc_threshold: log2fcThreshold,
                    padj_threshold: padjThreshold,
                  },
                })
              }
            >
              全遺伝子を CSV でダウンロード
            </button>
          </div>

          <p className="notes">{compare.data.note}</p>

          <div className="two-column">
            <PlotCard title="Volcano プロット">
              <Plot
                data={volcano}
                layout={{
                  xaxis: { title: "log2 fold change", zeroline: true },
                  yaxis: { title: "-log10(FDR)" },
                  legend: { orientation: "h", y: -0.22 },
                  shapes: [
                    { type: "line", x0: log2fcThreshold, x1: log2fcThreshold, yref: "paper", y0: 0, y1: 1, line: { dash: "dot", width: 1, color: "#9aa5b1" } },
                    { type: "line", x0: -log2fcThreshold, x1: -log2fcThreshold, yref: "paper", y0: 0, y1: 1, line: { dash: "dot", width: 1, color: "#9aa5b1" } },
                    { type: "line", xref: "paper", x0: 0, x1: 1, y0: -Math.log10(padjThreshold), y1: -Math.log10(padjThreshold), line: { dash: "dot", width: 1, color: "#9aa5b1" } },
                  ],
                }}
              />
            </PlotCard>
            <PlotCard title="MA プロット" description="平均発現量に対する変化量。低発現域のばらつきを確認できます。">
              <Plot
                data={maPlot}
                layout={{
                  xaxis: { title: "log2（平均発現量 + 1）" },
                  yaxis: { title: "log2 fold change", zeroline: true },
                  showlegend: false,
                }}
              />
            </PlotCard>
          </div>

          <section className="card">
            <div className="tabs">
              <button
                type="button"
                className={tab === "onthefly" ? "tab tab--active" : "tab"}
                onClick={() => setTab("onthefly")}
              >
                探索用統計（このサイトで計算）
              </button>
              <button
                type="button"
                className={tab === "registered" ? "tab tab--active" : "tab"}
                onClick={() => setTab("registered")}
              >
                厳密解析結果（登録済み DEG 表）
              </button>
            </div>

            {tab === "onthefly" ? (
              <>
                <p className="muted">
                  {compare.data.truncated
                    ? `全 ${compare.data.n_genes_total} 遺伝子のうち上位 ${rows.length} 件を表示しています。全件は CSV でダウンロードしてください。`
                    : `全 ${rows.length} 遺伝子。`}
                </p>
                <DegTable
                  rows={rows.slice(0, 200)}
                  log2fcThreshold={log2fcThreshold}
                  padjThreshold={padjThreshold}
                />
              </>
            ) : (
              <RegisteredTab
                comparisonId={comparisonId}
                onPick={(id) => url.patch({ comparison: id })}
                datasetId={caseSelection.dataset_id}
              />
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}

function DegTable({
  rows,
  log2fcThreshold,
  padjThreshold,
}: {
  rows: CompareRow[];
  log2fcThreshold: number;
  padjThreshold: number;
}) {
  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th>遺伝子</th>
            <th>log2FC</th>
            <th>case 平均</th>
            <th>control 平均</th>
            <th>p 値</th>
            <th>FDR</th>
            <th>効果量</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const significant =
              row.padj !== null && row.padj <= padjThreshold && Math.abs(row.log2fc) >= log2fcThreshold;
            return (
              <tr key={row.gene_id} className={significant ? "row--significant" : undefined}>
                <td>
                  <Link to={`/genes?gene=${encodeURIComponent(row.gene_id)}`}>{row.symbol}</Link>
                </td>
                <td className={`num ${row.log2fc > 0 ? "up" : "down"}`}>{formatNumber(row.log2fc, 2)}</td>
                <td className="num">{formatNumber(row.mean_case, 1)}</td>
                <td className="num">{formatNumber(row.mean_control, 1)}</td>
                <td className="num">{formatNumber(row.pvalue)}</td>
                <td className="num">{formatNumber(row.padj)}</td>
                <td className="num">{formatNumber(row.effect_size, 2)}</td>
                <td>{significant ? <Tag tone={row.log2fc > 0 ? "case" : "control"}>有意</Tag> : null}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RegisteredTab({
  comparisonId,
  onPick,
  datasetId,
}: {
  comparisonId: string;
  onPick: (id: string) => void;
  datasetId: string | null | undefined;
}) {
  const available = useQuery({
    queryKey: ["comparisons", datasetId],
    queryFn: () => api.comparisons(datasetId),
  });

  const query = useQuery({
    queryKey: ["degs", comparisonId],
    queryFn: () => api.degs(comparisonId),
    enabled: Boolean(comparisonId),
    retry: false,
  });

  return (
    <div>
      <p className="muted">
        DESeq2 / limma 等で作成した結果を <code>data/degs/</code> に登録すると、ここに表示されます。
        上のタブの探索用統計とは別に管理されます。
      </p>
      <Field label="登録済みの比較">
        <select value={comparisonId} onChange={(event) => onPick(event.target.value)}>
          <option value="">選択してください</option>
          {(available.data ?? [])
            .filter((comparison) => comparison.has_deg_table)
            .map((comparison) => (
              <option key={comparison.comparison_id} value={comparison.comparison_id}>
                {comparison.label ?? comparison.comparison_id}
              </option>
            ))}
        </select>
      </Field>

      {!comparisonId ? <Empty>登録済みの比較を選んでください。</Empty> : null}
      {query.isPending && comparisonId ? <Spinner /> : null}
      {query.error ? (
        <Empty>
          この比較の DEG 表は未登録です。<code>data/degs/{comparisonId}.csv</code> を配置してください。
        </Empty>
      ) : null}
      {query.data ? (
        <>
          <div className="toolbar">
            <button type="button" onClick={() => void downloadCsv("/export/degs", `${comparisonId}.csv`, { params: { comparison_id: comparisonId } })}>
              CSV でダウンロード
            </button>
          </div>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>遺伝子</th>
                  <th>log2FC</th>
                  <th>p 値</th>
                  <th>FDR</th>
                  <th>平均発現量</th>
                </tr>
              </thead>
              <tbody>
                {query.data.rows.slice(0, 200).map((row) => (
                  <tr key={row.gene_id}>
                    <td>
                      <Link to={`/genes?gene=${encodeURIComponent(row.gene_id)}`}>
                        {row.symbol ?? row.gene_id}
                      </Link>
                    </td>
                    <td className={`num ${row.log2fc > 0 ? "up" : "down"}`}>{formatNumber(row.log2fc, 2)}</td>
                    <td className="num">{formatNumber(row.pvalue)}</td>
                    <td className="num">{formatNumber(row.padj)}</td>
                    <td className="num">{formatNumber(row.base_mean, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </div>
  );
}
