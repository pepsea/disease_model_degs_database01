/** 比較の case / control を組み立てる。

「データセット → 臓器 → 群」で指定するか、個別サンプルを直接選ぶ。
両方の指定方法を 1 つの型（SampleSelection）に落とす。
*/

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api, type Dataset, type SampleSelection } from "../api/client";
import { Field, Select, Tag } from "./common";

export function GroupBuilder({
  title,
  datasets,
  value,
  onChange,
  disabled = false,
}: {
  title: string;
  datasets: Dataset[];
  value: SampleSelection;
  onChange: (next: SampleSelection) => void;
  disabled?: boolean;
}) {
  const [showSamples, setShowSamples] = useState(false);

  const { data: samples = [] } = useQuery({
    queryKey: ["samples", value.dataset_id],
    queryFn: () => api.samples({ dataset_id: value.dataset_id }),
    enabled: Boolean(value.dataset_id),
  });

  const organs = useMemo(
    () => Array.from(new Set(samples.map((s) => s.organ))).sort(),
    [samples],
  );

  const groups = useMemo(() => {
    const filtered = value.organ ? samples.filter((s) => s.organ === value.organ) : samples;
    const seen = new Map<string, boolean>();
    for (const sample of filtered) {
      if (!seen.has(sample.group_label)) seen.set(sample.group_label, sample.is_control);
    }
    return Array.from(seen.entries()).map(([label, isControl]) => ({
      value: label,
      label: isControl ? `${label}（対照）` : label,
    }));
  }, [samples, value.organ]);

  /** 現在の条件に一致するサンプル（個別選択の候補と件数表示に使う）。 */
  const matching = useMemo(() => {
    return samples.filter(
      (sample) =>
        (!value.organ || sample.organ === value.organ) &&
        (!value.group_label || sample.group_label === value.group_label) &&
        (!value.genotype || sample.genotype === value.genotype),
    );
  }, [samples, value.organ, value.group_label, value.genotype]);

  const selectedIds = value.sample_ids ?? [];
  const effectiveCount = selectedIds.length > 0 ? selectedIds.length : matching.length;

  function toggleSample(sampleId: string) {
    const next = selectedIds.includes(sampleId)
      ? selectedIds.filter((id) => id !== sampleId)
      : [...selectedIds, sampleId];
    onChange({ ...value, sample_ids: next.length ? next : null });
  }

  return (
    <fieldset className={`builder${disabled ? " builder--disabled" : ""}`} disabled={disabled}>
      <legend>{title}</legend>

      <div className="builder__row">
        <Field label="データセット">
          <Select
            value={value.dataset_id ?? ""}
            placeholder="選択してください"
            options={datasets.map((d) => ({ value: d.dataset_id, label: `${d.dataset_id} — ${d.title}` }))}
            onChange={(dataset_id) =>
              // データセットを変えたら下位の選択は無効になるため落とす
              onChange({ dataset_id: dataset_id || null, organ: null, group_label: null, sample_ids: null })
            }
          />
        </Field>
        <Field label="臓器">
          <Select
            value={value.organ ?? ""}
            options={organs}
            disabled={!value.dataset_id}
            onChange={(organ) => onChange({ ...value, organ: organ || null, group_label: null, sample_ids: null })}
          />
        </Field>
        <Field label="群">
          <Select
            value={value.group_label ?? ""}
            options={groups}
            disabled={!value.dataset_id}
            onChange={(group_label) => onChange({ ...value, group_label: group_label || null, sample_ids: null })}
          />
        </Field>
      </div>

      <div className="builder__footer">
        <span>
          対象サンプル <strong>{effectiveCount}</strong> 件
          {selectedIds.length > 0 ? <Tag tone="muted">個別選択</Tag> : null}
        </span>
        {matching.length > 0 ? (
          <button type="button" className="link" onClick={() => setShowSamples((open) => !open)}>
            {showSamples ? "個別選択を閉じる" : "個別サンプルを選ぶ"}
          </button>
        ) : null}
        {selectedIds.length > 0 ? (
          <button type="button" className="link" onClick={() => onChange({ ...value, sample_ids: null })}>
            個別選択を解除
          </button>
        ) : null}
      </div>

      {showSamples ? (
        <ul className="builder__samples">
          {matching.map((sample) => (
            <li key={sample.sample_id}>
              <label>
                <input
                  type="checkbox"
                  checked={selectedIds.includes(sample.sample_id)}
                  onChange={() => toggleSample(sample.sample_id)}
                />
                <code>{sample.sample_id}</code>
                <span className="muted">
                  {sample.organ} / {sample.group_label}
                  {sample.sex ? ` / ${sample.sex}` : ""}
                </span>
                {sample.is_control ? <Tag tone="control">対照</Tag> : null}
              </label>
            </li>
          ))}
        </ul>
      ) : null}
    </fieldset>
  );
}
