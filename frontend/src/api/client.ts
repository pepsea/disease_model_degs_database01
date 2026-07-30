/** API クライアントと応答の型。 */

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      // JSON でない応答はステータスのみ表示する
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const get = <T,>(path: string, params: Record<string, unknown> = {}) =>
  request<T>(`/api${path}${query(params as Record<string, string>)}`);

export const post = <T,>(path: string, body: unknown) =>
  request<T>(`/api${path}`, { method: "POST", body: JSON.stringify(body) });

/** CSV をダウンロードさせる（応答は JSON ではないため個別に処理する）。 */
export async function downloadCsv(
  path: string,
  filename: string,
  options: { method?: "GET" | "POST"; body?: unknown; params?: Record<string, unknown> } = {},
): Promise<void> {
  const method = options.method ?? "GET";
  const url = `/api${path}${method === "GET" ? query((options.params ?? {}) as Record<string, string>) : ""}`;
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: method === "POST" ? JSON.stringify(options.body) : undefined,
  });
  if (!response.ok) throw new ApiError(`ダウンロードに失敗しました (${response.status})`, response.status);
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
}

// ---- 型 ---------------------------------------------------------------

export interface Facets {
  species: string[];
  assays: string[];
  disease_categories: string[];
  modalities: string[];
  organs: string[];
  genotypes: string[];
}

export interface Model {
  model_id: string;
  model_name: string;
  species: string;
  modality: string;
  disease_category: string;
  strain: string | null;
  target_gene: string | null;
  description: string | null;
  reference_url: string | null;
  n_datasets: number;
  n_samples: number;
}

export interface Dataset {
  dataset_id: string;
  title: string;
  model_id: string;
  model_name: string | null;
  disease_category: string | null;
  modality: string | null;
  species: string;
  assay: string;
  unit: string;
  gene_id_type: string;
  platform: string | null;
  pmid: string | null;
  geo_url: string | null;
  notes: string | null;
  n_samples: number;
  n_controls: number;
  organs: string[] | null;
  groups: string[] | null;
}

export interface Sample {
  sample_id: string;
  dataset_id: string;
  model_id: string;
  model_name: string | null;
  group_label: string;
  genotype: string;
  is_control: boolean;
  organ: string;
  tissue_detail: string | null;
  sex: string | null;
  age_weeks: number | null;
  treatment: string | null;
  replicate: string | null;
  batch: string | null;
  library_size: number | null;
  detected_genes: number | null;
  unit: string | null;
}

export interface GroupSummary {
  organ: string;
  group_label: string;
  n_samples: number;
  is_control: boolean;
  genotype: string;
}

export interface Comparison {
  comparison_id: string;
  dataset_id: string;
  case_group_label: string;
  control_group_label: string;
  organ: string | null;
  method: string | null;
  label: string | null;
  has_deg_table: boolean;
  dataset_title?: string | null;
}

export interface DatasetDetail {
  dataset: Dataset;
  samples: Sample[];
  groups: GroupSummary[];
  comparisons: Comparison[];
}

export interface Gene {
  gene_id: string;
  symbol: string;
  name: string | null;
  species: string | null;
  biotype: string | null;
}

export interface ExpressionPoint {
  gene_id: string;
  sample_id: string;
  raw_value: number;
  value: number;
  dataset_id: string;
  organ: string;
  group_label: string;
  genotype: string;
  is_control: boolean;
  sex: string | null;
  treatment: string | null;
  batch: string | null;
  unit: string;
  dataset_title: string;
  model_name: string | null;
  disease_category: string | null;
}

export interface GroupStat {
  dataset_id: string;
  organ: string;
  n: number;
  mean: number;
  median: number;
  sd: number | null;
  min: number;
  max: number;
  [key: string]: unknown;
}

export interface GeneExpressionResponse {
  gene: Gene;
  group_by: string;
  points: ExpressionPoint[];
  summary: GroupStat[];
  units: string[];
  note: string;
}

export interface ForestRow {
  dataset_id: string;
  organ: string;
  group_label: string;
  model_name: string;
  disease_category: string;
  n_case: number;
  n_control: number;
  mean_case: number;
  mean_control: number;
  log2fc: number;
  unit: string;
}

export interface SampleSelection {
  sample_ids?: string[] | null;
  dataset_id?: string | null;
  group_label?: string | null;
  organ?: string | null;
  genotype?: string | null;
}

export interface CompareRow {
  gene_id: string;
  symbol: string;
  log2fc: number;
  mean_case: number;
  mean_control: number;
  base_mean: number;
  pvalue: number | null;
  padj: number | null;
  effect_size: number | null;
  n_case: number;
  n_control: number;
}

export interface CompareResponse {
  rows: CompareRow[];
  summary: {
    n_genes: number;
    n_tested: number;
    n_up: number;
    n_down: number;
    log2fc_threshold: number;
    padj_threshold: number;
  };
  method: string;
  control_auto_selected: boolean;
  case_samples: Sample[];
  control_samples: Sample[];
  warnings: string[];
  n_genes_total: number;
  truncated: boolean;
  note: string;
}

export interface DegRow {
  gene_id: string;
  symbol: string;
  log2fc: number;
  pvalue: number | null;
  padj: number | null;
  base_mean: number | null;
}

export interface PcaResponse {
  samples: Array<{ sample_id: string } & Record<string, number | string>>;
  explained_variance_ratio: number[];
  components: string[];
  n_genes: number;
  loadings: Array<{ component: string; genes: Array<{ gene_id: string; loading: number }> }>;
  scaled_within_datasets?: boolean;
  samples_meta: Sample[];
  warnings: string[];
  message?: string;
}

export interface HeatmapResponse {
  genes: string[];
  samples: string[];
  values: (number | null)[][];
  scaled_within_datasets?: boolean;
  samples_meta: Sample[];
  warnings: string[];
  message?: string;
}

export interface CorrelationResponse {
  samples: string[];
  matrix: (number | null)[][];
  method: string;
  samples_meta: Sample[];
  warnings: string[];
  message?: string;
}

export interface StatusResponse {
  generated_at: string | null;
  data_dir?: string;
  counts: Record<string, number>;
  datasets: Record<string, { n_genes: number; n_samples: number; source_file: string }>;
  issues: Array<{ level: string; file: string; row: number | null; column: string | null; message: string }>;
  message?: string;
}

// ---- エンドポイント ---------------------------------------------------

export const api = {
  status: () => get<StatusResponse>("/status"),
  facets: () => get<Facets>("/facets"),
  models: () => get<Model[]>("/models"),
  datasets: (params: Record<string, unknown>) => get<Dataset[]>("/datasets", params),
  datasetDetail: (id: string) => get<DatasetDetail>(`/datasets/${encodeURIComponent(id)}`),
  samples: (params: Record<string, unknown>) => get<Sample[]>("/samples", params),
  comparisons: (datasetId?: string | null) =>
    get<Comparison[]>("/comparisons", datasetId ? { dataset_id: datasetId } : {}),
  searchGenes: (q: string) => get<Gene[]>("/genes/search", { q, limit: 20 }),
  geneExpression: (params: Record<string, unknown>) =>
    get<GeneExpressionResponse>("/expression/gene", params),
  geneAcrossModels: (params: Record<string, unknown>) =>
    get<{ gene: string; rows: ForestRow[] }>("/expression/gene/across-models", params),
  compare: (body: unknown) => post<CompareResponse>("/compare", body),
  degs: (comparisonId: string) =>
    get<{ comparison: Comparison; rows: DegRow[] }>("/degs", { comparison_id: comparisonId }),
  pca: (body: unknown) => post<PcaResponse>("/analysis/pca", body),
  heatmap: (body: unknown) => post<HeatmapResponse>("/analysis/heatmap", body),
  correlation: (body: unknown) => post<CorrelationResponse>("/analysis/correlation", body),
};
