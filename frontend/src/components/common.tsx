/** 画面をまたいで使う小さな部品。 */

import type { ReactNode } from "react";

export function Spinner({ label = "読み込み中…" }: { label?: string }) {
  return (
    <div className="state state--loading" role="status">
      {label}
    </div>
  );
}

export function ErrorBox({ error, hint }: { error: unknown; hint?: string }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="state state--error" role="alert">
      <strong>エラー</strong>
      <p>{message}</p>
      {hint ? <p className="muted">{hint}</p> : null}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="state state--empty">{children}</div>;
}

/** 解析結果に付随する注意喚起（バッチ交絡・単位混在など）。 */
export function Warnings({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="warnings" role="note">
      <strong>解釈上の注意</strong>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

export function PlotCard({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card">
      <header className="card__header">
        <div>
          <h2>{title}</h2>
          {description ? <p className="muted">{description}</p> : null}
        </div>
        {actions ? <div className="card__actions">{actions}</div> : null}
      </header>
      {children}
    </section>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span className="field__label">{label}</span>
      {children}
    </label>
  );
}

export function Select({
  value,
  onChange,
  options,
  placeholder = "すべて",
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  options: Array<string | { value: string; label: string }>;
  placeholder?: string;
  disabled?: boolean;
}) {
  return (
    <select value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled}>
      <option value="">{placeholder}</option>
      {options.map((option) => {
        const item = typeof option === "string" ? { value: option, label: option } : option;
        return (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        );
      })}
    </select>
  );
}

export function Tag({ children, tone }: { children: ReactNode; tone?: "control" | "case" | "muted" }) {
  return <span className={`tag${tone ? ` tag--${tone}` : ""}`}>{children}</span>;
}

/** 数値の表示。指数が必要な桁は指数で出す。 */
export function formatNumber(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const magnitude = Math.abs(value);
  if (magnitude !== 0 && (magnitude < 1e-3 || magnitude >= 1e6)) return value.toExponential(2);
  return value.toFixed(digits);
}
