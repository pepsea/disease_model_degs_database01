/** 解析画面: 任意サンプル集合の PCA / 相関 / ヒートマップ。 */

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api, type Sample } from "../api/client";
import { Plot } from "../charts/Plot";
import { ErrorBox, Field, PlotCard, Select, Spinner, Warnings } from "../components/common";
import { useUrlState } from "../lib/useUrlState";

const COLOR_BY_OPTIONS = [
  { value: "organ", label: "臓器" },
  { value: "group_label", label: "群" },
  { value: "genotype", label: "遺伝型" },
  { value: "dataset_id", label: "データセット" },
  { value: "model_name", label: "モデル" },
  { value: "batch", label: "バッチ" },
  { value: "sex", label: "性別" },
];

export function Analysis() {
  const url = useUrlState();
  const datasetId = url.get("dataset");
  const organ = url.get("organ");
  const colorBy = url.get("color_by", "organ");
  const topGenes = url.getNumber("top", 2000);
  const scaleWithin = url.getBool("scale", false);
  const pcX = url.get("pcx", "PC1");
  const pcY = url.get("pcy", "PC2");

  const facets = useQuery({ queryKey: ["facets"], queryFn: api.facets });
  const datasets = useQuery({ queryKey: ["datasets", {}], queryFn: () => api.datasets({}) });

  const selection = { dataset_id: datasetId || null, organ: organ || null };

  const pca = useQuery({
    queryKey: ["analysis-pca", datasetId, organ, topGenes, scaleWithin],
    queryFn: () =>
      api.pca({
        selection,
        n_top_genes: topGenes,
        n_components: 5,
        scale_within_datasets: scaleWithin,
      }),
  });

  const correlation = useQuery({
    queryKey: ["analysis-corr", datasetId, organ, topGenes],
    queryFn: () => api.correlation({ selection, n_top_genes: topGenes, method: "spearman" }),
  });

  const heatmap = useQuery({
    queryKey: ["analysis-heatmap", datasetId, organ, scaleWithin],
    queryFn: () => api.heatmap({ selection, n_top_genes: 50, scale_within_datasets: scaleWithin }),
  });

  const metaById = useMemo(
    () => new Map((pca.data?.samples_meta ?? []).map((sample) => [sample.sample_id, sample])),
    [pca.data],
  );

  const scatter = useMemo(() => {
    const samples = pca.data?.samples ?? [];
    if (!samples.length) return [];
    const groups = new Map<string, { x: number[]; y: number[]; text: string[] }>();
    for (const row of samples) {
      const meta = metaById.get(row.sample_id);
      const key = meta ? String((meta as unknown as Record<string, unknown>)[colorBy] ?? "未設定") : "不明";
      const entry = groups.get(key) ?? { x: [], y: [], text: [] };
      entry.x.push(Number(row[pcX] ?? 0));
      entry.y.push(Number(row[pcY] ?? 0));
      entry.text.push(describe(meta, row.sample_id));
      groups.set(key, entry);
    }
    return Array.from(groups.entries()).map(([name, entry]) => ({
      type: "scatter",
      mode: "markers",
      name,
      x: entry.x,
      y: entry.y,
      text: entry.text,
      hovertemplate: `%{text}<br>${pcX} %{x:.2f}<br>${pcY} %{y:.2f}<extra>${name}</extra>`,
      marker: { size: 11, line: { width: 1, color: "#fff" } },
    }));
  }, [pca.data, metaById, colorBy, pcX, pcY]);

  const ratios = pca.data?.explained_variance_ratio ?? [];
  const components = pca.data?.components ?? ["PC1", "PC2"];
  const ratioOf = (component: string) => {
    const index = components.indexOf(component);
    return index >= 0 ? (ratios[index] ?? 0) : 0;
  };

  const scree = ratios.length
    ? [
        {
          type: "bar",
          x: components,
          y: ratios.map((r) => r * 100),
          hovertemplate: "%{x}<br>%{y:.1f}%<extra></extra>",
          marker: { color: "#5b8def" },
        },
      ]
    : [];

  return (
    <div className="content content--wide">
      <h1>解析</h1>
      <p className="muted">
        条件を指定しない場合は登録済みの全サンプルを対象にします。研究をまたぐ場合は
        「データセット内 z-score」を有効にすると、バッチ差の影響を抑えた比較になります。
      </p>

      <div className="toolbar">
        <Field label="データセット">
          <Select
            value={datasetId}
            options={(datasets.data ?? []).map((d) => ({ value: d.dataset_id, label: d.dataset_id }))}
            onChange={(value) => url.patch({ dataset: value })}
          />
        </Field>
        <Field label="臓器">
          <Select
            value={organ}
            options={facets.data?.organs ?? []}
            onChange={(value) => url.patch({ organ: value })}
          />
        </Field>
        <Field label="色分け">
          <Select
            value={colorBy}
            placeholder="臓器"
            options={COLOR_BY_OPTIONS}
            onChange={(value) => url.patch({ color_by: value || "organ" })}
          />
        </Field>
        <Field label="高変動遺伝子数">
          <input
            type="number"
            min={10}
            max={20000}
            step={100}
            value={topGenes}
            onChange={(event) => url.patch({ top: event.target.value })}
          />
        </Field>
        <Field label="横軸">
          <Select value={pcX} placeholder="PC1" options={components} onChange={(v) => url.patch({ pcx: v || "PC1" })} />
        </Field>
        <Field label="縦軸">
          <Select value={pcY} placeholder="PC2" options={components} onChange={(v) => url.patch({ pcy: v || "PC2" })} />
        </Field>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={scaleWithin}
            onChange={(event) => url.patch({ scale: event.target.checked ? "1" : "0" })}
          />
          データセット内 z-score
        </label>
      </div>

      {pca.error ? <ErrorBox error={pca.error} /> : null}
      <Warnings items={pca.data?.warnings ?? []} />

      <div className="two-column">
        <PlotCard
          title="主成分分析"
          description={
            pca.data ? `高変動遺伝子 ${pca.data.n_genes} 個・サンプル ${pca.data.samples.length} 件` : undefined
          }
        >
          {pca.isPending ? <Spinner /> : null}
          {scatter.length ? (
            <Plot
              data={scatter}
              height={440}
              layout={{
                xaxis: { title: `${pcX} (${(ratioOf(pcX) * 100).toFixed(1)}%)`, zeroline: true },
                yaxis: { title: `${pcY} (${(ratioOf(pcY) * 100).toFixed(1)}%)`, zeroline: true },
                legend: { orientation: "h", y: -0.2 },
              }}
            />
          ) : null}
        </PlotCard>

        <PlotCard title="寄与率" description="各主成分が説明する分散の割合。">
          {scree.length ? (
            <Plot
              data={scree}
              height={440}
              layout={{ yaxis: { title: "寄与率 (%)" }, showlegend: false }}
            />
          ) : null}
        </PlotCard>
      </div>

      <PlotCard
        title="サンプル間相関と階層クラスタリング"
        description="Spearman 相関。並び順は平均連結法によるクラスタリング順。"
      >
        {correlation.isPending ? <Spinner /> : null}
        {correlation.error ? <ErrorBox error={correlation.error} /> : null}
        {correlation.data?.matrix.length ? (
          <Plot
            height={Math.min(900, Math.max(360, correlation.data.samples.length * 22 + 160))}
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
            layout={{ margin: { l: 120, r: 20, t: 10, b: 130 }, xaxis: { tickangle: -45 } }}
          />
        ) : null}
      </PlotCard>

      <PlotCard
        title="発現全体像（高変動遺伝子上位 50）"
        description="遺伝子ごとに z-score 化し、遺伝子・サンプルともクラスタリング順に並べています。"
      >
        {heatmap.isPending ? <Spinner /> : null}
        {heatmap.error ? <ErrorBox error={heatmap.error} /> : null}
        {heatmap.data?.values.length ? (
          <Plot
            height={820}
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
            layout={{ margin: { l: 110, r: 20, t: 10, b: 130 }, xaxis: { tickangle: -45 } }}
          />
        ) : null}
      </PlotCard>
    </div>
  );
}

function describe(sample: Sample | undefined, sampleId: string): string {
  if (!sample) return sampleId;
  return `${sampleId}<br>${sample.dataset_id} / ${sample.organ} / ${sample.group_label}`;
}
