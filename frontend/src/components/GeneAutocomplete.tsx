/** 遺伝子名の入力補助。 */

import { useEffect, useRef, useState } from "react";
import { api, type Gene } from "../api/client";

export function GeneAutocomplete({
  value,
  onSelect,
  placeholder = "遺伝子名（例: Lcn2）",
}: {
  value: string;
  onSelect: (geneId: string) => void;
  placeholder?: string;
}) {
  const [text, setText] = useState(value);
  const [options, setOptions] = useState<Gene[]>([]);
  const [open, setOpen] = useState(false);
  const wrapper = useRef<HTMLDivElement | null>(null);

  // 外から value が変わったら同期する（URL 復元時など）
  useEffect(() => setText(value), [value]);

  useEffect(() => {
    if (!text || text === value) {
      setOptions([]);
      return;
    }
    let cancelled = false;
    // 入力ごとにリクエストを飛ばさないよう少し待つ
    const timer = setTimeout(() => {
      api
        .searchGenes(text)
        .then((rows) => {
          if (!cancelled) {
            setOptions(rows);
            setOpen(rows.length > 0);
          }
        })
        .catch(() => {
          if (!cancelled) setOptions([]);
        });
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [text, value]);

  // 外側クリックで候補を閉じる
  useEffect(() => {
    function handler(event: MouseEvent) {
      if (wrapper.current && !wrapper.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  function choose(geneId: string) {
    setText(geneId);
    setOpen(false);
    onSelect(geneId);
  }

  return (
    <div className="autocomplete" ref={wrapper}>
      <input
        type="text"
        value={text}
        placeholder={placeholder}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            choose(options[0]?.gene_id ?? text);
          }
          if (event.key === "Escape") setOpen(false);
        }}
      />
      {open ? (
        <ul className="autocomplete__list">
          {options.map((gene) => (
            <li key={gene.gene_id}>
              <button type="button" onClick={() => choose(gene.gene_id)}>
                <strong>{gene.symbol}</strong>
                {gene.name ? <span className="muted"> {gene.name}</span> : null}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
