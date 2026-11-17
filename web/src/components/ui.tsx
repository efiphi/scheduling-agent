import { useId, type ReactNode } from "react";

// Small building blocks shared by the screens, so every screen looks and behaves the same.

export const NOT_CONNECTED = "יחובר בשכבה 1";

export function Card({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="mb-4 rounded-xl border border-slate-200 bg-white p-4">
      <h2 id={id} className="mb-2 font-semibold">
        {title}
      </h2>
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-slate-600">{children}</p>;
}

/** A control that exists in the structure but does nothing until the API is connected. */
export function PendingButton({ children, tone = "default" }: { children: ReactNode; tone?: "default" | "danger" | "primary" }) {
  const tones = {
    default: "border border-slate-300",
    primary: "bg-blue-700 text-white",
    danger: "border border-red-300 text-red-800",
  };
  return (
    <button type="button" disabled title={NOT_CONNECTED} className={`rounded-lg px-4 py-2 disabled:opacity-50 ${tones[tone]}`}>
      {children}
    </button>
  );
}

/** A labelled, read-only field. Values from outside are wrapped in <bdi> by the caller when needed. */
export function Field({ label, children, hint }: { label: string; children?: ReactNode; hint?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 border-b border-slate-100 py-2 last:border-b-0">
      <dt className="text-slate-700">{label}</dt>
      <dd className="text-start">
        {children ?? <span className="text-slate-400">—</span>}
        {hint && <span className="block text-xs text-slate-500">{hint}</span>}
      </dd>
    </div>
  );
}
