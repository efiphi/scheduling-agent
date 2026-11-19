import { useId, type ReactNode } from "react";

import { buttonClass } from "./styles";

// Small building blocks shared by the screens, so every screen looks and behaves the same.
// Colors come from the theme tokens in index.css.

export const NOT_CONNECTED = "יחובר בשכבה 1";


export function Card({ title, children, subtitle }: { title: string; children: ReactNode; subtitle?: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="mb-3.5 rounded-[var(--radius-card)] border border-line bg-surface p-4">
      <h2 id={id} className="text-base font-semibold">
        {title}
      </h2>
      {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-[var(--radius-card)] border border-dashed border-line-strong bg-surface/60 px-4 py-8 text-center text-muted">
      {children}
    </p>
  );
}

/** A control that exists in the structure but does nothing until the API is connected. */
export function PendingButton({ children, tone = "default" }: { children: ReactNode; tone?: "default" | "danger" | "primary" }) {
  const tones = { default: buttonClass.secondary, primary: buttonClass.primary, danger: buttonClass.danger };
  return (
    <button type="button" disabled title={NOT_CONNECTED} className={tones[tone]}>
      {children}
    </button>
  );
}

/** A labelled, read-only field. Values from outside are wrapped in <bdi> by the caller when needed. */
export function Field({ label, children, hint }: { label: string; children?: ReactNode; hint?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 border-b border-line-soft py-3 first:pt-0 last:border-b-0 last:pb-0">
      <dt className="text-ink-soft">{label}</dt>
      <dd className="text-start font-medium">
        {children ?? <span className="font-normal text-muted">—</span>}
        {hint && <span className="block text-xs font-normal text-muted">{hint}</span>}
      </dd>
    </div>
  );
}

/** A short message after an action: success (status) or a problem (alert). */
export function Notice({ tone, children }: { tone: "ok" | "warn" | "danger"; children: ReactNode }) {
  const tones = {
    ok: "bg-ok-bg text-ok",
    warn: "bg-warn-bg text-warn-ink",
    danger: "bg-danger-bg text-danger",
  };
  return (
    <p role={tone === "ok" ? "status" : "alert"} className={`mb-4 rounded-xl px-3 py-2.5 text-sm ${tones[tone]}`}>
      {children}
    </p>
  );
}

/** Line icons (stroke, 24×24), decorative: the text next to them carries the meaning. */
export function Icon({ name, className = "size-5" }: { name: IconName; className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className={className}>
      {icons[name]}
    </svg>
  );
}

const icons = {
  queue: (
    <>
      <path d="M9 11l3 3 8-8" />
      <path d="M20 12v7a2 2 0 01-2 2H6a2 2 0 01-2-2V5a2 2 0 012-2h9" />
    </>
  ),
  history: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  contacts: (
    <>
      <circle cx="9" cy="8" r="3.5" />
      <path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6" />
      <path d="M16 4.5a3.5 3.5 0 010 7" />
      <path d="M18 14.5c1.8.8 3 2.6 3 4.5" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z" />
    </>
  ),
  mail: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M3 7l9 6 9-6" />
    </>
  ),
  calendar: (
    <>
      <rect x="3" y="4" width="18" height="17" rx="2" />
      <path d="M16 2v4M8 2v4M3 10h18" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3l7 3v6c0 4.5-3 7.8-7 9-4-1.2-7-4.5-7-9V6l7-3z" />
      <path d="M9 12l2 2 4-4" />
    </>
  ),
  warning: (
    <>
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
      <path d="M10.3 3.9L2.4 18a2 2 0 001.7 3h15.8a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" />
    </>
  ),
  check: <path d="M5 12l5 5L20 7" />,
  send: (
    <>
      <path d="M22 2L11 13" />
      <path d="M22 2l-7 20-4-9-9-4 20-7z" />
    </>
  ),
  cross: <path d="M18 6L6 18M6 6l12 12" />,
  pause: (
    <>
      <rect x="6" y="5" width="4" height="14" rx="1" />
      <rect x="14" y="5" width="4" height="14" rx="1" />
    </>
  ),
  back: <path d="M9 6l6 6-6 6" />,
  chevron: <path d="M15 6l-6 6 6 6" />,
  dot: <path d="M5 12h14" />,
} as const;

export type IconName = keyof typeof icons;

/** A rounded square holding an icon, in front of a card's or a row's title. */
export function IconTile({ name, tone = "accent" }: { name: IconName; tone?: "accent" | "ok" | "danger" | "muted" }) {
  const tones = {
    accent: "bg-accent-soft text-accent",
    ok: "bg-ok-bg text-ok",
    danger: "bg-danger-bg text-danger",
    muted: "bg-line-soft text-muted",
  };
  return (
    <span className={`flex size-9 flex-none items-center justify-center rounded-xl ${tones[tone]}`}>
      <Icon name={name} className="size-[18px]" />
    </span>
  );
}
