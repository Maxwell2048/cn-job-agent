import { type ReactNode, useEffect } from "react";

type Tone = "neutral" | "good" | "warn" | "bad" | "info" | "accent";

const TONES: Record<string, Tone> = {
  // posting / run status
  new: "info", review: "warn", screened_out: "neutral", matched: "good", failed: "bad",
  running: "accent", interrupted: "warn", rejected: "neutral", done: "good",
  // decisions and verdicts
  pass: "good", reject: "bad", error: "bad",
  direct: "good", related: "warn", insufficient: "bad",
  // severity
  hard: "bad", soft: "warn", info: "neutral",
  // cohort
  eligible: "good", boundary: "warn", likely: "info", conditional: "warn", unknown: "neutral", ineligible: "bad",
};

export function Badge({ value, children, tone }: { value?: string | null; children: ReactNode; tone?: Tone }) {
  return <span className={`badge tone-${tone ?? TONES[value ?? ""] ?? "neutral"}`}>{children}</span>;
}

export function Score({ score, label, compact = false }:
  { score: number | null | undefined; label?: string | null; compact?: boolean }) {
  if (score == null) return <span className="muted">—</span>;
  const tone = score >= 70 ? "good" : score >= 50 ? "accent" : score >= 30 ? "warn" : "bad";
  if (compact) return <Badge tone={tone}>{score}</Badge>;
  return (
    <span className="score" title="证据覆盖分数，不是录用概率">
      <span className="score-track">
        <span className={`score-fill tone-${tone}`} style={{ width: `${Math.max(4, score)}%` }} />
      </span>
      <span className="score-number">{score}</span>
      {label && <span className="muted small">{label}</span>}
    </span>
  );
}

export function Card({ title, actions, children, className = "" }:
  { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-header">
          {title && <h2>{title}</h2>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: string; tone?: Tone }) {
  return (
    <div className={`stat ${tone ? `stat-${tone}` : ""}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="error-box" role="alert">{error}</div>;
}

export function Loading() {
  return <div className="loading" aria-busy="true">加载中…</div>;
}

export function Quote({ children, source }: { children: ReactNode; source?: ReactNode }) {
  return (
    <blockquote className="quote">
      <div>{children}</div>
      {source && <cite>{source}</cite>}
    </blockquote>
  );
}

export function Tabs<T extends string>({ tabs, active, onChange }:
  { tabs: { key: T; label: ReactNode }[]; active: T; onChange: (key: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button key={tab.key} role="tab" aria-selected={tab.key === active}
                className={tab.key === active ? "tab active" : "tab"} onClick={() => onChange(tab.key)}>
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const close = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(e) => e.stopPropagation()}>
        <header className="card-header">
          <h2>{title}</h2>
          <button className="icon-button" onClick={onClose} aria-label="关闭">×</button>
        </header>
        {children}
      </div>
    </div>
  );
}
