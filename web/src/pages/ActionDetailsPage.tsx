import { Link, useLoaderData } from "react-router";

import { ActionCard } from "../components/ActionCard";
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
    <section className="space-y-4">
      <BackLink />
      <ActionCard action={action} />

      {action.explanation && (
        <section aria-labelledby="explanation-title">
          <h2 id="explanation-title" className="mb-1 font-semibold">
            למה הסוכן הציע את זה
          </h2>
          <p className="text-slate-700" dir="auto">
            {action.explanation}
          </p>
        </section>
      )}

      {action.source && (
        <section aria-labelledby="source-title" className="rounded-xl border border-slate-200 bg-white p-4">
          <h2 id="source-title" className="mb-2 font-semibold">
            ההודעה המקורית
          </h2>
          <dl className="mb-2 text-sm text-slate-600">
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
          <p className="whitespace-pre-wrap text-sm" dir="auto">
            {action.source.text}
          </p>
        </section>
      )}
    </section>
  );
}

function BackLink() {
  return (
    <Link to="/" className="text-blue-700 underline">
      חזרה לתור
    </Link>
  );
}
