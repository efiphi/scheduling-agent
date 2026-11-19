import { useState } from "react";
import { Link } from "react-router";

import { useDataSource } from "../data/context";

import { actionKindLabel, type IncomingEmail, type PendingAction } from "../domain/actions";
import { formatDateTime } from "../lib/time";
import { Icon, IconTile, PendingButton, type IconName } from "./ui";
import { buttonClass } from "./styles";
import { SlotTime } from "./SlotTime";

// The card must allow a decision without opening another screen (docs/04-web-app.md).
// Everything that came from outside is rendered as text; English inside Hebrew is
// wrapped in <bdi> so addresses and times keep their direction.
export function ActionCard({
  action,
  onDecided,
}: {
  action: PendingAction;
  /** Called after the server accepted the decision, so the queue can drop the card. */
  onDecided?: (id: string, decision: "approved" | "rejected") => void;
}) {
  const expired = action.status === "expired";
  const failed = action.status === "failed";
  // Only what needs the owner's eye gets color: a failure, an unusual request.
  const border = failed ? "border-danger-line" : action.anomalyReason ? "border-warn-line" : "border-line";

  return (
    <article
      aria-labelledby={`action-${action.id}-title`}
      className={`flex flex-col gap-3.5 rounded-[var(--radius-card)] border bg-surface p-4 shadow-[var(--shadow-card)] ${border} ${expired ? "opacity-75" : ""}`}
    >
      {/* The validity sits under the title, so a long date never squeezes the title. */}
      <header className="flex items-center gap-2.5">
        <IconTile name={kindIcon[action.kind]} />
        <div className="min-w-0">
          <h2 id={`action-${action.id}-title`} className="text-base leading-snug font-semibold">
            <Link to={`/actions/${action.id}`} className="hover:text-accent">
              {actionKindLabel[action.kind]}
            </Link>
          </h2>
          <p className="text-xs text-muted">{expired ? "פג" : `בתוקף עד ${formatDateTime(action.expiresAt)}`}</p>
        </div>
      </header>

      {failed && (
        // E13: no failure disappears silently; the reason is in plain language.
        <p role="alert" className="flex gap-2.5 rounded-xl bg-danger-bg px-3 py-2.5 text-sm leading-relaxed text-danger">
          <Icon name="warning" className="mt-0.5 size-[18px] flex-none" />
          <span>
            <span className="font-semibold">נכשל: </span>
            {action.failureReason ?? "הביצוע נכשל."}
          </span>
        </p>
      )}

      {expired && (
        // E7: an expired action is locked; it can only go back to the queue as a new pending action.
        <p role="status" className="rounded-xl bg-sunken px-3 py-2.5 text-sm text-ink-soft">
          הפעולה פגה. אפשר להחזיר אותה לתור.
        </p>
      )}

      {action.anomalyReason && (
        <p role="note" className="flex gap-2.5 rounded-xl bg-warn-bg px-3 py-2.5 text-sm leading-relaxed text-warn-ink">
          <Icon name="warning" className="mt-0.5 size-[18px] flex-none text-warn-icon" />
          <span>
            <span className="font-semibold">בקשה חריגה: </span>
            {action.anomalyReason}
          </span>
        </p>
      )}

      {action.incoming && <IncomingEmailDetails email={action.incoming} />}

      {action.recipients.length > 0 && (
        <section aria-label="נמענים" className="flex flex-col gap-2">
          <p className="text-[0.8125rem] text-muted">נמענים</p>
          <ul className="flex flex-wrap gap-2">
            {action.recipients.map((r) => (
              <li
                key={r.email}
                className={`flex flex-wrap items-center gap-1.5 rounded-xl border px-2.5 py-1.5 text-[0.8125rem] ${
                  r.isNew ? "border-danger-line bg-danger-bg" : "border-line"
                }`}
              >
                {r.contactName && <span className="font-medium">{r.contactName}</span>}
                <bdi className={r.contactName ? "text-muted" : ""}>{r.email}</bdi>
                {r.isNew && (
                  <span className="rounded-md bg-danger px-1.5 py-px text-[0.6875rem] font-semibold text-white">נמען חדש</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {action.slots.length > 0 && (
        <section aria-label="מועדים" className="flex flex-col gap-2">
          <p className="text-[0.8125rem] text-muted">מועדים</p>
          <ul className="flex flex-col gap-2">
            {action.slots.map((s) => (
              <li key={s.start} className="rounded-xl border border-line px-3 py-2.5 text-[0.9375rem] font-medium">
                <SlotTime slot={s} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {action.draft && (
        <details className="group rounded-xl border border-line">
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between px-3 text-sm font-medium">
            הטיוטה המלאה
            <Icon name="chevron" className="size-4 text-muted transition-transform group-open:-rotate-90" />
          </summary>
          <p className="border-t border-line-soft px-3 py-3 text-sm leading-relaxed whitespace-pre-wrap" dir="auto">
            {action.draft}
          </p>
        </details>
      )}

      {action.flaggedSentences.length > 0 && (
        <section aria-label="משפטים שחורגים מתיאום" className="rounded-xl bg-warn-bg px-3 py-2.5 text-sm text-warn-ink">
          <p className="font-semibold">משפטים שחורגים מתיאום מועדים:</p>
          <ul className="mt-1 list-disc ps-5">
            {action.flaggedSentences.map((s) => (
              <li key={s} dir="auto">
                {s}
              </li>
            ))}
          </ul>
        </section>
      )}

      {expired ? <PendingButton>החזר לתור</PendingButton> : <ActionButtons action={action} onDecided={onDecided} />}
    </article>
  );
}

const kindIcon: Record<PendingAction["kind"], IconName> = {
  reply_with_slots: "mail",
  create_event: "calendar",
  reschedule_event: "calendar",
  cancel_event: "cross",
  block_time: "calendar",
};

// The email this action answers, so the decision does not need another screen (ADR-019).
// All of it is plain text (T19, T31).
function IncomingEmailDetails({ email }: { email: IncomingEmail }) {
  return (
    <section aria-label="המייל שהתקבל" className="flex flex-col gap-1.5 rounded-2xl bg-sunken p-3 text-sm">
      <p>
        <span className="text-muted">מאת </span>
        <bdi className="font-medium">{email.sender}</bdi>
      </p>
      <p dir="auto" className="font-medium">
        <span className="sr-only">נושא: </span>
        {email.subject}
      </p>
      {email.summary ? (
        <>
          <p className="mt-1 text-xs text-muted">תקציר של הסוכן · מתוך תוכן חיצוני, לא מאומת</p>
          <p dir="auto" className="leading-relaxed">
            {email.summary}
          </p>
        </>
      ) : (
        <p className="mt-1 text-ink-soft">אין תקציר למייל הזה. כדאי לקרוא אותו במקור.</p>
      )}
    </section>
  );
}

const decisionErrors: Record<string, string> = {
  hash_mismatch: "התוכן השתנה מאז שהוצג. רעננו את הדף.",
  expired: "הפעולה פגה.",
  not_pending: "הפעולה כבר טופלה.",
  "the agent is paused": "הסוכן מושהה.",
};

// Approve sends the content hash of exactly this card: the server refuses if the content
// changed in between (T3, T10). Edit comes after the MVP.
function ActionButtons({
  action,
  onDecided,
}: {
  action: PendingAction;
  onDecided?: (id: string, decision: "approved" | "rejected") => void;
}) {
  const source = useDataSource();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  async function decide(decision: "approved" | "rejected") {
    setBusy(true);
    setError(undefined);
    const result = decision === "approved" ? await source.approve(action.id, action.contentHash) : await source.reject(action.id);
    setBusy(false);
    if (result.ok) onDecided?.(action.id, decision);
    else setError(decisionErrors[result.reason] ?? "הפעולה נכשלה. נסו שוב.");
  }

  return (
    <>
      {error && (
        <p role="alert" className="rounded-xl bg-danger-bg px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <button type="button" disabled={busy} onClick={() => void decide("approved")} className={`${buttonClass.primary} flex-[2] px-3`}>
          אשר
        </button>
        <button type="button" disabled title="עריכה תגיע אחרי ה-MVP" className={`${buttonClass.secondary} flex-1 px-3`}>
          ערוך
        </button>
        <button type="button" disabled={busy} onClick={() => void decide("rejected")} className={`${buttonClass.danger} flex-1 px-3`}>
          דחה
        </button>
      </div>
    </>
  );
}
