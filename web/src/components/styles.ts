// Class strings shared by components (kept apart from them so Fast Refresh works).
// Colors are the theme tokens in index.css.

/** Button styles, for <button> and for links that act as buttons. */
export const buttonClass = {
  primary:
    "inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl bg-accent px-5 font-semibold text-white transition-colors hover:bg-accent-hover disabled:opacity-50",
  secondary:
    "inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl border border-line-strong bg-surface px-5 font-medium text-ink transition-colors hover:bg-sunken disabled:opacity-50",
  danger:
    "inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl border border-line-strong bg-surface px-5 font-medium text-danger transition-colors hover:bg-danger-bg disabled:opacity-50",
  dangerStrong:
    "inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl border-[1.5px] border-danger bg-surface px-5 font-semibold text-danger transition-colors hover:bg-danger-bg disabled:opacity-50",
  link: "font-medium text-accent underline-offset-4 hover:text-accent-hover hover:underline",
} as const;
