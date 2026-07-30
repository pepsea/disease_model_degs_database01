// plotly.js-dist-min は型定義を同梱していないため、必要な最小限だけ宣言する。
declare module "plotly.js-dist-min" {
  export function react(
    root: HTMLElement,
    data: unknown[],
    layout?: Record<string, unknown>,
    config?: Record<string, unknown>,
  ): Promise<void>;
  export function purge(root: HTMLElement): void;
  export function Plots(): void;
  const Plotly: {
    react: typeof react;
    purge: typeof purge;
    relayout: (root: HTMLElement, layout: Record<string, unknown>) => Promise<void>;
  };
  export default Plotly;
}
