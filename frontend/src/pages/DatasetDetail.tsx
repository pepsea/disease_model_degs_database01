/** データセット詳細: サンプル表 + 発現全体像（ヒートマップ・相関）。 */

import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api, downloadCsv } from "../api/client";
import { Plot } from "../charts/Plot";
import { ErrorBox, Field, PlotCard, Spinner, Tag, Warnings, formatNumber } from "../components/common";
import { useUrlState } from "../lib/useUrlState";

export function DatasetDetail() {
  const { datasetId = "" } = useParams();
  const url = useUrlState();
  const organ = url.get("organ");
  const topGenes = url.getNumber("top", 50);

  const detail = useQuery({
    queryKey: ["dataset", datasetId],
    queryFn: () => api.datasetDetail(datasetId),
  });

  const selection = { dataset_id: datasetId, organ: organ || null };

  const heatmap = useQuery({
    queryKey: ["heatmap", datasetId, organ, topGenes],
    queryFn: () => api.heatmap({ selection, n_top_genes: topGenes }),
    enabled: Boolean(detail.data),
  });

  const correlation = useQuery({
    queryKey: ["correlation", datasetId, organ],
    queryFn: () => api.correlation({ selection, method: "spearman" }),
    enabled: Boolean(detail.data),
  });

  const pca = useQuery({
    queryKey: ["dataset-pca", datasetId, organ],
    queryFn: () => api.pca({ selection, n_top_genes: 1000, n_components: 3 }),
    enabled: Boolean(detail.data),
  });

  if (detail.isPending) return <Spinner />;
  if (detail.error) return <ErrorBox error={detail.error} />;
  if (!detail.data) return null;

  const { dataset, samples, groups, comparisons } = detail.data;
  const organs = Array.from(new Set(samples.map((s) => s.organ))).sort();

  // PCA を臓器・群で色分けするための対応表
  const meta = new Map((pca.data?.samples_meta ?? []).map((s) => [s.sample_id, s]));
  const pcaTraces = (() => {
    if (!pca.data?.samples.length) return [];
    const byGroup = new Map<string, { x: number[]; y: number[]; text: string[] }>();
    for (const row of pca.data.samples) {
      const sample = meta.get(row.sample_id);
      const key = sample ? `${sample.organ} / ${sample.group_label}` : "不明";
      const entry = byGroup.get(key) ?? { x: [], y: [], text: [] };
      entry.x.push(Number(row.PC1));
      entry.y.push(Number(row.PC2));
      entry.text.push(row.sample_id);
      byGroup.set(key, entry);
    }
    return Array.from(byGroup.entries()).map(([name, entry]) => ({
      type: "scatter",
      mode: "markers",
      name,
      x: entry.x,
      y: entry.y,
      text: entry.text,
      hovertemplate: "%{text}<br>PC1 %{x:.2f}<br>PC2 %{y:.2f}<extra>" + name + "</extra>",
      marker: { size: 11, line: { width: 1, color: "#fff" } },
    }));
  })();

  const ratios = pca.data?.explained_variance_ratio ?? [];

  return (
    <div className="content content--wide">
      <nav className="breadcrumb">
        <Link to="/">データセット一覧</Link> / {dataset.dataset_id}
      </nav>

      <header className="page-header">
        <h1>{dataset.title}</h1>
        <p className="muted">
          {dataset.dataset_id} ・ {dataset.model_name} ・ {dataset.species} ・ {dataset.assay} ・ 単位{" "}
          {dataset.unit}
          {dataset.platform ? ` ・ ${dataset.platform}` : ""}
        </p>
        {dataset.notes ? <p className="notes">{dataset.notes}</p> : null}
        {dataset.geo_url ? (
          <p>
            <a href={dataset.geo_url} target="_blank" rel="noreferrer noopener">
              GEO で見る
            </a>
          </p>
        ) : null}
      </header>

      <div className="toolbar">
        <Field label="臓器で絞る">
          <select value={organ} onChange={(event) => url.patch({ organ: event.target.value })}>
            <option value="">すべて</option>
            {organs.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="ヒートマップの遺伝子数">
          <input
            type="number"
            min={2}
            max={500}
            value={topGenes}
            onChange={(event) => url.patch({ top: event.target.value })}
          />
        </Field>
        <button
          type="button"
          onClick={() =>
            void downloadCsv("/export/samples", `${datasetId}_samples.csv`, {
              params: { dataset_id: datasetId, organ: organ || undefined },
            })
          }
        >
          サンプル表を CSV でダウンロード
        </button>
      </div>

      <PlotCard
        title="群構成"
        description="比較の単位になる群と、対照（is_control=TRUE）の有無。"
      >
        <table className="table">
          <thead>
            <tr>
              <th>臓器</th>
              <th>群</th>
              <th>遺伝型</th>
              <th>サンプル数</th>
              <th>役割</th>
              <th>比較</th>
            </tr>
          </thead>
          <tbody>
            {groups
              .filter((group) => !organ || group.organ === organ)
              .map((group) => (
                <tr key={`${group.organ}-${group.group_label}`}>
                  <td>{group.organ}</td>
                  <td>{group.group_label}</td>
                  <td>{group.genotype}</td>
                  <td>{group.n_samples}</td>
                  <td>{group.is_control ? <Tag tone="control">対照</Tag> : <Tag tone="case">疾患・処置</Tag>}</td>
                  <td>
                    {group.is_control ? (
                      <span className="muted">—</span>
                    ) : (
                      <Link
                        to={`/compare?case_dataset=${datasetId}&case_group=${encodeURIComponent(
                          group.group_label,
                        )}&case_organ=${encodeURIComponent(group.organ)}`}
                      >
                        WT と比較
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </PlotCard>

      {comparisons.length > 0 ? (
        <PlotCard title="登録済みの比較" description="外部解析（DESeq2 等）の結果が登録されている比較。">
          <ul className="list">
            {comparisons.map((comparison) => (
              <li key={comparison.comparison_id}>
                <Link to={`/compare?comparison=${comparison.comparison_id}`}>
                  {comparison.label ?? comparison.comparison_id}
                </Link>{" "}
                <span className="muted">
                  {comparison.case_group_label} vs {comparison.control_group_label}
                  {comparison.method ? ` ・ ${comparison.method}` : ""}
                </span>
                {comparison.has_deg_table ? <Tag>DEG 表あり</Tag> : <Tag tone="muted">DEG 表なし</Tag>}
              </li>
            ))}
          </ul>
        </PlotCard>
      ) : null}

      <PlotCard
        title="発現全体像（高変動遺伝子ヒートマップ）"
        description={`変動の大きい上位 ${topGenes} 遺伝子。遺伝子ごとに z-score 化し、階層クラスタリングで並べ替えています。`}
      >
        {heatmap.isPending ? <Spinner /> : null}
        {heatmap.error ? <ErrorBox error={heatmap.error} /> : null}
        <Warnings items={heatmap.data?.warnings ?? []} />
        {heatmap.data?.values.length ? (
          <Plot
            height={Math.min(1000, Math.max(340, heatmap.data.genes.length * 14 + 120))}
            data={[
              {
                type: "heatmap",
                z: heatmap.data.values,
                x: heatmap.data.samples,
                y: heatmap.data.genes,
                colorscale: "RdBu",
                reversescale: true,
                zmid: 0,
                colorbar: { title: "z-score" },
                hovertemplate: "%{y}<br>%{x}<br>z = %{z:.2f}<extra></extra>",
              },
            ]}
            layout={{ margin: { l: 110, r: 20, t: 10, b: 120 }, xaxis: { tickangle: -45 } }}
          />
        ) : null}
      </PlotCard>

      <div className="two-column">
        <PlotCard
          title="主成分分析"
          description={
            ratios.length
              ? `PC1 ${(ratios[0] * 100).toFixed(1)}% / PC2 ${(ratios[1] * 100).toFixed(1)}%`
              : undefined
          }
        >
          {pca.isPending ? <Spinner /> : null}
          {pca.error ? <ErrorBox error={pca.error} /> : null}
          <Warnings items={pca.data?.warnings ?? []} />
          {pcaTraces.length ? (
            <Plot
              data={pcaTraces}
              layout={{
                xaxis: { title: `PC1 (${((ratios[0] ?? 0) * 100).toFixed(1)}%)`, zeroline: true },
                yaxis: { title: `PC2 (${((ratios[1] ?? 0) * 100).toFixed(1)}%)`, zeroline: true },
                legend: { orientation: "h", y: -0.25 },
              }}
            />
          ) : null}
        </PlotCard>

        <PlotCard title="サンプル間相関" description="Spearman 相関。階層クラスタリング順に並べています。">
          {correlation.isPending ? <Spinner /> : null}
          {correlation.error ? <ErrorBox error={correlation.error} /> : null}
          {correlation.data?.matrix.length ? (
            <Plot
              data={[
                {
                  type: "heatmap",
                  z: correlation.data.matrix,
                  x: correlation.data.samples,
                  y: correlation.data.samples,
                  colorscale: "Viridis",
                  colorbar: { title: "ρ" },
                  hovertemplate: "%{y}<br>%{x}<br>ρ = %{z:.3f}<extra></extra>",
                },
              ]}
              layout={{ margin: { l: 110, r: 20, t: 10, b: 120 }, xaxis: { tickangle: -45 } }}
            />
          ) : null}
        </PlotCard>
      </div>

      <PlotCard title="サンプル一覧" description="個別サンプルの属性と取り込み時の集計値。">
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>サンプル</th>
                <th>臓器</th>
                <th>群</th>
                <th>遺伝型</th>
                <th>対照</th>
                <th>性別</th>
                <th>週齢</th>
                <th>バッチ</th>
                <th>ライブラリサイズ</th>
                <th>検出遺伝子数</th>
              </tr>
            </thead>
            <tbody>
              {samples
                .filter((sample) => !organ || sample.organ === organ)
                .map((sample) => (
                  <tr key={sample.sample_id}>
                    <td>
                      <code>{sample.sample_id}</code>
                    </td>
                    <td>{sample.organ}</td>
                    <td>{sample.group_label}</td>
                    <td>{sample.genotype}</td>
                    <td>{sample.is_control ? "✓" : ""}</td>
                    <td>{sample.sex ?? "—"}</td>
                    <td>{sample.age_weeks ?? "—"}</td>
                    <td>{sample.batch ?? "—"}</td>
                    <td className="num">{formatNumber(sample.library_size, 0)}</td>
                    <td className="num">{sample.detected_genes ?? "—"}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </PlotCard>
    </div>
  );
}
