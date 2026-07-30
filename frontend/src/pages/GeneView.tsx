/** 遺伝子ごとの発現量とモデル横断の WT 比。 */

import { useQuery } from "@tanstack/react-query";
import { api, downloadCsv } from "../api/client";
import { Plot } from "../charts/Plot";
import { Empty, ErrorBox, Field, PlotCard, Select, Spinner, Warnings, formatNumber } from "../components/common";
import { GeneAutocomplete } from "../components/GeneAutocomplete";
import { useUrlState } from "../lib/useUrlState";

const GROUP_BY_OPTIONS = [
  { value: "group_label", label: "群" },
  { value: "genotype", label: "遺伝型" },
  { value: "organ", label: "臓器" },
  { value: "dataset_id", label: "データセット" },
  { value: "sex", label: "性別" },
  { value: "treatment", label: "処置" },
  { value: "batch", label: "バッチ" },
];

export function GeneView() {
  const url = useUrlState();
  const gene = url.get("gene");
  const datasetId = url.get("dataset");
  const organ = url.get("organ");
  const groupBy = url.get("group_by", "group_label");

  const facets = useQuery({ queryKey: ["facets"], queryFn: api.facets });
  const datasets = useQuery({ queryKey: ["datasets", {}], queryFn: () => api.datasets({}) });

  const expression = useQuery({
    queryKey: ["gene-expression", gene, datasetId, organ, groupBy],
    queryFn: () =>
      api.geneExpression({
        gene,
        dataset_id: datasetId || undefined,
        organ: organ || undefined,
        group_by: groupBy,
      }),
    enabled: Boolean(gene),
  });

  const forest = useQuery({
    queryKey: ["gene-forest", gene, organ],
    queryFn: () => api.geneAcrossModels({ gene, organ: organ || undefined }),
    enabled: Boolean(gene),
    retry: false,
  });

  // 群ごとの箱ひげ + 個別サンプルの重ね描き
  const boxTraces = (() => {
    const points = expression.data?.points ?? [];
    if (!points.length) return [];
    const groups = new Map<string, { y: number[]; text: string[]; isControl: boolean }>();
    for (const point of points) {
      const key = String((point as unknown as Record<string, unknown>)[groupBy] ?? "不明");
      const label = datasetId ? key : `${point.dataset_id} / ${key}`;
      const entry = groups.get(label) ?? { y: [], text: [], isControl: point.is_control };
      entry.y.push(point.value);
      entry.text.push(`${point.sample_id} (${point.organ})`);
      groups.set(label, entry);
    }
    return Array.from(groups.entries()).map(([name, entry]) => ({
      type: "box",
      name,
      y: entry.y,
      text: entry.text,
      boxpoints: "all",
      jitter: 0.5,
      pointpos: 0,
      marker: { size: 7, color: entry.isControl ? "#5b8def" : "#e2725b" },
      line: { color: entry.isControl ? "#3f6fd1" : "#c4553c" },
      hovertemplate: "%{text}<br>%{y:.2f}<extra>" + name + "</extra>",
    }));
  })();

  const forestTrace = (() => {
    const rows = forest.data?.rows ?? [];
    if (!rows.length) return [];
    return [
      {
        type: "bar",
        orientation: "h",
        x: rows.map((row) => row.log2fc),
        y: rows.map((row) => `${row.dataset_id} / ${row.organ} / ${row.group_label}`),
        text: rows.map((row) => `${row.model_name} (n=${row.n_case} vs ${row.n_control})`),
        hovertemplate: "%{y}<br>log2FC %{x:.2f}<br>%{text}<extra></extra>",
        marker: {
          color: rows.map((row) => (row.log2fc >= 0 ? "#e2725b" : "#5b8def")),
        },
      },
    ];
  })();

  return (
    <div className="content content--wide">
      <h1>遺伝子ごとの発現量</h1>

      <div className="toolbar">
        <Field label="遺伝子">
          <GeneAutocomplete value={gene} onSelect={(value) => url.patch({ gene: value })} />
        </Field>
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
        <Field label="群分け">
          <Select
            value={groupBy}
            placeholder="群"
            options={GROUP_BY_OPTIONS}
            onChange={(value) => url.patch({ group_by: value || "group_label" })}
          />
        </Field>
        {gene ? (
          <button
            type="button"
            onClick={() =>
              void downloadCsv("/export/gene", `${gene}_expression.csv`, {
                params: { gene, dataset_id: datasetId || undefined, organ: organ || undefined },
              })
            }
          >
            CSV でダウンロード
          </button>
        ) : null}
      </div>

      {!gene ? <Empty>上の入力欄で遺伝子を指定してください。</Empty> : null}

      {gene ? (
        <>
          {expression.isPending ? <Spinner /> : null}
          {expression.error ? (
            <ErrorBox
              error={expression.error}
              hint="遺伝子名は登録データの gene_id と一致する必要があります（大小文字は区別しません）。"
            />
          ) : null}

          {expression.data ? (
            <>
              <header className="page-header">
                <h2>
                  {expression.data.gene.symbol}
                  {expression.data.gene.name ? (
                    <span className="muted"> — {expression.data.gene.name}</span>
                  ) : null}
                </h2>
                <p className="muted">{expression.data.note}</p>
              </header>

              {expression.data.units.length > 1 ? (
                <Warnings
                  items={[
                    `表示中のデータに複数の単位が含まれます（${expression.data.units.join(
                      ", ",
                    )}）。単位が異なるデータ間の絶対値比較はできません。データセットで絞ると単位が揃います。`,
                  ]}
                />
              ) : null}

              <PlotCard
                title="群別の発現量"
                description="点は個別サンプル。青が対照、赤が疾患・処置群。"
              >
                <Plot
                  data={boxTraces}
                  height={420}
                  layout={{
                    yaxis: { title: expression.data.units[0] === "log2_intensity" ? "log2 強度" : "CPM / TPM" },
                    xaxis: { tickangle: -25 },
                    showlegend: false,
                  }}
                />
              </PlotCard>

              <PlotCard title="群ごとの要約統計">
                <div className="table-scroll">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>データセット</th>
                        <th>臓器</th>
                        <th>{GROUP_BY_OPTIONS.find((o) => o.value === groupBy)?.label ?? groupBy}</th>
                        <th>n</th>
                        <th>平均</th>
                        <th>中央値</th>
                        <th>SD</th>
                        <th>最小</th>
                        <th>最大</th>
                      </tr>
                    </thead>
                    <tbody>
                      {expression.data.summary.map((row, index) => (
                        <tr key={index}>
                          <td>{row.dataset_id}</td>
                          <td>{row.organ}</td>
                          <td>{String(row[groupBy] ?? "—")}</td>
                          <td className="num">{row.n}</td>
                          <td className="num">{formatNumber(row.mean, 2)}</td>
                          <td className="num">{formatNumber(row.median, 2)}</td>
                          <td className="num">{formatNumber(row.sd, 2)}</td>
                          <td className="num">{formatNumber(row.min, 2)}</td>
                          <td className="num">{formatNumber(row.max, 2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </PlotCard>
            </>
          ) : null}

          <PlotCard
            title="モデル横断の WT 比"
            description="各データセット内の対照サンプルを基準に log2FC を計算しています。データセット内で比を取るため、研究間のバッチ差の影響を受けにくい形で並べられます。"
          >
            {forest.isPending ? <Spinner /> : null}
            {forest.error ? (
              <Empty>
                この遺伝子について WT 比を計算できる組み合わせがありません。各データセットに
                <code>is_control=TRUE</code> のサンプルが必要です。
              </Empty>
            ) : null}
            {forestTrace.length ? (
              <Plot
                data={forestTrace}
                height={Math.max(280, (forest.data?.rows.length ?? 0) * 42 + 120)}
                layout={{
                  xaxis: { title: "log2 fold change（対 WT）", zeroline: true, zerolinewidth: 2 },
                  margin: { l: 280, r: 30, t: 10, b: 50 },
                }}
              />
            ) : null}
          </PlotCard>
        </>
      ) : null}
    </div>
  );
}
