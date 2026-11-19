import type { ReactNode } from "react";

/** The screen's one <h1>, with an optional line above it (a date, a parent screen). */
export function PageTitle({ children, eyebrow }: { children: string; eyebrow?: ReactNode }) {
  return (
    <header className="mb-5">
      {eyebrow && <p className="mb-0.5 text-sm text-muted">{eyebrow}</p>}
      <h1 className="text-[1.75rem] leading-tight font-bold tracking-tight">{children}</h1>
    </header>
  );
}
