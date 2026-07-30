/** ブラウズ画面: ファセット絞り込みとデータセット一覧。 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Empty, ErrorBox, Field, Select, Spinner, Tag } from "../components/common";
import { useUrlState } from "../lib/useUrlState";

export function Browse() {
  const url = useUrlState();
  const filters = {
    species: url.get("species"),
    organ: url.get("organ"),
    disease_category: url.get("category"),
    assay: url.get("assay"),
    model_id: url.get("model"),
    q: url.get("q"),
  };

  const facets = useQuery({ queryKey: ["facets"], queryFn: api.facets });
  const models = useQuery({ queryKey: ["models"], queryFn: api.models });
  const status = useQuery({ queryKey: ["status"], queryFn: api.status });
  const datasets = useQuery({
    queryKey: ["datasets", filters],
    queryFn: () => api.datasets(filters),
  });

  const counts = status.data?.counts ?? {};
  const warningCount = (status.data?.issues ?? []).filter((i) => i.level === "warning").length;

  return (
    <div className="layout">
      <aside className="sidebar">
        <h2>絞り込み</h2>
        <Field label="キーワード">
          <input
            type="search"
            value={filters.q}
            placeholder="タイトル / GSE / モデル名"
            onChange={(event) => url.patch({ q: event.target.value })}
          />
        </Field>
        <Field label="疾患カテゴリ">
          <Select
            value={filters.disease_category}
            options={facets.data?.disease_categories ?? []}
            onChange={(value) => url.patch({ category: value })}
          />
        </Field>
        <Field label="モデル">
          <Select
            value={filters.model_id}
            options={(models.data ?? []).map((m) => ({ value: m.model_id, label: m.model_name }))}
            onChange={(value) => url.patch({ model: value })}
          />
        </Field>
        <Field label="臓器">
          <Select
            value={filters.organ}
            options={facets.data?.organs ?? []}
            onChange={(value) => url.patch({ organ: value })}
          />
        </Field>
        <Field label="種">
          <Select
            value={filters.species}
            options={facets.data?.species ?? []}
            onChange={(value) => url.patch({ species: value })}
          />
        </Field>
        <Field label="アッセイ">
          <Select
            value={filters.assay}
            options={facets.data?.assays ?? []}
            onChange={(value) => url.patch({ assay: value })}
          />
        </Field>
        <button
          type="button"
          className="link"
          onClick={() =>
            url.patch({ q: "", category: "", model: "", organ: "", species: "", assay: "" })
          }
        >
          条件をクリア
        </button>

        <div className="sidebar__status">
          <h3>収載状況</h3>
          <dl>
            <dt>データセット</dt>
            <dd>{counts.datasets ?? 0}</dd>
            <dt>サンプル</dt>
            <dd>{counts.samples ?? 0}</dd>
            <dt>モデル</dt>
            <dd>{counts.models ?? 0}</dd>
            <dt>遺伝子</dt>
            <dd>{counts.genes ?? 0}</dd>
          </dl>
          {status.data?.generated_at ? (
            <p className="muted">取り込み: {new Date(status.data.generated_at).toLocaleString("ja-JP")}</p>
          ) : (
            <p className="muted">まだ取り込みが実行されていません。</p>
          )}
          {warningCount > 0 ? (
            <p className="muted">
              取り込み時の警告 {warningCount} 件（<Link to="/docs">詳細</Link>）
            </p>
          ) : null}
        </div>
      </aside>

      <main className="content">
        <h1>データセット一覧</h1>
        {datasets.isPending ? <Spinner /> : null}
        {datasets.error ? <ErrorBox error={datasets.error} /> : null}
        {datasets.data?.length === 0 ? (
          <Empty>
            {counts.datasets === 0 ? (
              <>
                <p>まだデータが登録されていません。</p>
                <p className="muted">
                  <code>data/</code> に CSV を置いて <code>python -m dmdeg.ingest</code> を実行してください。
                  手順は<Link to="/docs">データ登録方法</Link>にあります。
                </p>
              </>
            ) : (
              <p>条件に一致するデータセットがありません。</p>
            )}
          </Empty>
        ) : null}

        <div className="grid">
          {(datasets.data ?? []).map((dataset) => (
            <article className="dataset" key={dataset.dataset_id}>
              <header>
                <Link className="dataset__id" to={`/datasets/${dataset.dataset_id}`}>
                  {dataset.dataset_id}
                </Link>
                {dataset.disease_category ? <Tag>{dataset.disease_category}</Tag> : null}
                <Tag tone="muted">{dataset.assay}</Tag>
              </header>
              <h3>
                <Link to={`/datasets/${dataset.dataset_id}`}>{dataset.title}</Link>
              </h3>
              <dl className="dataset__meta">
                <dt>モデル</dt>
                <dd>{dataset.model_name ?? dataset.model_id}</dd>
                <dt>臓器</dt>
                <dd>{dataset.organs?.join(", ") ?? "—"}</dd>
                <dt>サンプル</dt>
                <dd>
                  {dataset.n_samples} 件（対照 {dataset.n_controls} 件）
                </dd>
                <dt>単位</dt>
                <dd>{dataset.unit}</dd>
              </dl>
              {dataset.n_controls === 0 ? (
                <p className="dataset__warn">
                  対照サンプルが未登録のため、WT の自動選択ができません。
                </p>
              ) : null}
            </article>
          ))}
        </div>
      </main>
    </div>
  );
}
