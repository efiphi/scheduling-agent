import { Link } from "react-router";

import { actionKindLabel, type PendingAction } from "../domain/actions";
import { formatDateTime } from "../lib/time";
import { PendingButton } from "./ui";
import { SlotTime } from "./SlotTime";

// The card must allow a decision without opening another screen (docs/04-web-app.md).
// Everything that came from outside is rendered as text; English inside Hebrew is
// wrapped in <bdi> so addresses and times keep their direction.
export function ActionCard({ action }: { action: PendingAction }) {
  const expired = action.status === "expired";
  const failed = action.status === "failed";
  const border = failed ? "border-red-400" : action.anomalyReason ? "border-amber-400" : "border-slate-200";

  return (
    <article
      aria-labelledby={`action-${action.id}-title`}
      className={`rounded-xl border bg-white p-4 shadow-sm ${border} ${expired ? "opacity-75" : ""}`}
    >
      <header className="mb-3 flex items-baseline justify-between gap-2">
        <h2 id={`action-${action.id}-title`} className="text-lg font-semibold">
          <Link to={`/actions/${action.id}`}>{actionKindLabel[action.kind]}</Link>
        </h2>
        <p className="text-sm text-slate-600">
          {expired ? "פג" : `בתוקף עד ${formatDateTime(action.expiresAt)}`}
        </p>
      </header>

      {failed && (
        // E13: no failure disappears silently; the reason is in plain language.
        <p role="alert" className="mb-3 rounded-lg bg-red-50 p-2 text-sm text-red-900">
          <span className="font-semibold">נכשל: </span>
          {action.failureReason ?? "הביצוע נכשל."}
        </p>
      )}

      {expired && (
        // E7: an expired action is locked; it can only go back to the queue as a new pending action.
        <p role="status" className="mb-3 rounded-lg bg-slate-100 p-2 text-sm text-slate-800">
          הפעולה פגה. אפשר להחזיר אותה לתור.
        </p>
      )}

      {action.anomalyReason && (
        <p role="note" className="mb-3 rounded-lg bg-amber-50 p-2 text-sm text-amber-900">
          <span className="font-semibold">בקשה חריגה: </span>
          {action.anomalyReason}
        </p>
      )}

      {action.recipients.length > 0 && (
        <section aria-label="נמענים" className="mb-3">
          <ul className="space-y-1">
            {action.recipients.map((r) => (
              <li key={r.email} className="flex flex-wrap items-center gap-2">
                {r.contactName && <span className="font-medium">{r.contactName}</span>}
                <bdi className="text-slate-700">{r.email}</bdi>
                {r.isNew && (
                  <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-800">נמען חדש</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {action.slots.length > 0 && (
        <section aria-label="מועדים" className="mb-3">
          <ul className="space-y-1">
            {action.slots.map((s) => (
              <li key={s.start}>
                <SlotTime slot={s} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {action.draft && (
        <details className="mb-3">
          <summary className="cursor-pointer text-sm text-slate-700">הטיוטה המלאה</summary>
          <p className="mt-2 whitespace-pre-wrap rounded-lg bg-slate-50 p-2 text-sm" dir="auto">
            {action.draft}
          </p>
        </details>
      )}

      {action.flaggedSentences.length > 0 && (
        <section aria-label="משפטים שחורגים מתיאום" className="mb-3 text-sm">
          <p className="font-semibold text-amber-900">משפטים שחורגים מתיאום מועדים:</p>
          <ul className="list-disc ps-5">
            {action.flaggedSentences.map((s) => (
              <li key={s} dir="auto">
                {s}
              </li>
            ))}
          </ul>
        </section>
      )}

      {expired ? <PendingButton>החזר לתור</PendingButton> : <ActionButtons />}
    </article>
  );
}

// Approve / edit / reject are not wired until the API exists (Layer 1).
function ActionButtons() {
  const note = "יחובר בשכבה 1";
  return (
    <div className="flex gap-2">
      <button type="button" disabled title={note} className="flex-1 rounded-lg bg-blue-700 py-2 text-white disabled:opacity-50">
        אשר
      </button>
      <button type="button" disabled title={note} className="flex-1 rounded-lg border border-slate-300 py-2 disabled:opacity-50">
        ערוך
      </button>
      <button type="button" disabled title={note} className="flex-1 rounded-lg border border-slate-300 py-2 disabled:opacity-50">
        דחה
      </button>
    </div>
  );
}
