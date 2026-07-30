/** Plotly の薄いラッパ。 */

import { useEffect, useRef } from "react";
import Plotly from "plotly.js-dist-min";

const BASE_CONFIG = {
  displaylogo: false,
  responsive: true,
  toImageButtonOptions: { format: "svg", scale: 2 },
  modeBarButtonsToRemove: ["lasso2d", "select2d"],
};

const BASE_LAYOUT = {
  font: { family: "system-ui, -apple-system, 'Hiragino Sans', 'Noto Sans JP', sans-serif", size: 12 },
  margin: { l: 60, r: 20, t: 30, b: 60 },
  paper_bgcolor: "transparent",
  plot_bgcolor: "transparent",
  hovermode: "closest",
};

export interface PlotProps {
  data: unknown[];
  layout?: Record<string, unknown>;
  height?: number;
}

export function Plot({ data, layout = {}, height = 380 }: PlotProps) {
  const container = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = container.current;
    if (!node) return;
    void Plotly.react(node, data, { ...BASE_LAYOUT, height, ...layout }, BASE_CONFIG);
  }, [data, layout, height]);

  // アンマウント時に Plotly の内部状態を解放する
  useEffect(() => {
    const node = container.current;
    return () => {
      if (node) Plotly.purge(node);
    };
  }, []);

  return <div ref={container} style={{ width: "100%", height }} />;
}
