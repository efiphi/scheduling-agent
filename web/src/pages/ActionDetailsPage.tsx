import { Link, useLoaderData } from "react-router";

import { ActionCard } from "../components/ActionCard";
import { Icon } from "../components/ui";
import { buttonClass } from "../components/styles";
import type { PendingAction } from "../domain/actions";
import { formatDateTime } from "../lib/time";
import { PageTitle } from "./PageTitle";

// Everything on the card, plus the original message as clean text and the agent's reasoning.
export function ActionDetailsPage() {
  const action = useLoaderData<PendingAction | null>();

  if (!action) {
    return (
      <section>
        <PageTitle>הפעולה לא נמצאה</PageTitle>
        <BackLink />
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-3.5">
      <BackLink />
      <ActionCard action={action} />

      {action.explanation && (
        <section aria-labelledby="explanation-title" className="rounded-[var(--radius-card)] border border-line bg-surface p-4">
          <h2 id="explanation-title" className="mb-1.5 text-[0.9375rem] font-semibold">
            למה הסוכן הציע את זה
          </h2>
          <p className="text-sm leading-relaxed text-ink-soft" dir="auto">
            {action.explanation}
          </p>
        </section>
      )}

      {action.source && (
        <section aria-labelledby="source-title" className="rounded-[var(--radius-card)] border border-line bg-surface p-4">
          <h2 id="source-title" className="mb-2 text-[0.9375rem] font-semibold">
            ההודעה המקורית
          </h2>
          <dl className="mb-3 text-sm text-muted">
            <dt className="inline">מאת: </dt>
            <dd className="inline">
              <bdi>{action.source.from}</bdi>
            </dd>
            {action.source.subject && (
              <>
                <br />
                <dt className="inline">נושא: </dt>
                <dd className="inline" dir="auto">
                  {action.source.subject}
                </dd>
              </>
            )}
            <br />
            <dt className="inline">התקבלה: </dt>
            <dd className="inline">{formatDateTime(action.source.receivedAt)}</dd>
          </dl>
          {/* T19: untrusted content is text only; links are not made clickable. */}
          <p className="rounded-xl bg-sunken p-3 text-sm leading-relaxed whitespace-pre-wrap" dir="auto">
            {action.source.text}
          </p>
          <p className="mt-2 text-xs text-muted">המייל מוצג כטקסט בלבד. קישורים בו לא לחיצים.</p>
        </section>
      )}
    </section>
  );
}

function BackLink() {
  return (
    <Link to="/" className={`${buttonClass.secondary} min-h-11 self-start rounded-full px-4 text-sm`}>
      <Icon name="back" className="size-4" />
      חזרה לתור
    </Link>
  );
}
