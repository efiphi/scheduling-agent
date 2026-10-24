import type { Account } from "../domain/account";
import { useOnline } from "../lib/online";
import { PendingButton } from "./ui";

// Account-wide states shown at the top of every screen (docs/04-web-app.md, "special states").
// Most severe first. With no account loaded (nothing connected yet) only "offline" can show.
export function StatusBanners({ account }: { account: Account | null }) {
  const online = useOnline();

  return (
    <div className="space-y-px">
      {account?.agentStatus === "paused" && (
        // T11, ADR-014: paused by the stop code or the pause button. Resuming needs a fresh login.
        <Banner tone="danger" label="הסוכן מושהה">
          <p>הסוכן מושהה וכל הפעולות הממתינות בוטלו. חזרה לפעולה דורשת התחברות מחדש.</p>
          <PendingButton>החזר לפעולה</PendingButton>
        </Banner>
      )}

      {account && account.google !== "connected" && (
        // E13: in Google's testing mode the connection expires every 7 days.
        <Banner tone="warning" label="החיבור ל-Google">
          <p>{account.google === "expired" ? "החיבור ל-Google פג." : "Google לא מחובר."} הסוכן לא יכול לקרוא מיילים או לבדוק את היומן.</p>
          <PendingButton>חיבור מחדש</PendingButton>
        </Banner>
      )}

      {account?.spendCapReached && (
        // T24: the daily LLM spend cap stops processing of new emails until tomorrow.
        <Banner tone="warning" label="תקרת הוצאה">
          <p>הסוכן עצר לעיבוד מיילים חדשים עד מחר.</p>
        </Banner>
      )}

      {!online && (
        <Banner tone="muted" label="אין חיבור לרשת">
          <p>אין חיבור לרשת. מוצגים הנתונים האחרונים, והכפתורים נעולים עד שהחיבור יחזור.</p>
        </Banner>
      )}
    </div>
  );
}

const tones = {
  danger: "bg-red-700 text-white",
  warning: "bg-amber-100 text-amber-950",
  muted: "bg-slate-200 text-slate-900",
};

function Banner({ tone, label, children }: { tone: keyof typeof tones; label: string; children: React.ReactNode }) {
  return (
    <section role="alert" aria-label={label} className={`${tones[tone]} px-4 py-3 text-sm`}>
      <div className="mx-auto flex max-w-xl flex-wrap items-center justify-between gap-2">{children}</div>
    </section>
  );
}
