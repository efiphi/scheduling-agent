import { useEffect, useState } from "react";
import { Link, useLoaderData } from "react-router";

import { ActionCard } from "../components/ActionCard";
import { useDataSource } from "../data/context";
import { byExpiry, type PendingAction } from "../domain/actions";
import { applyQueueEvent, type QueueState } from "../domain/queue";
import { PageTitle } from "./PageTitle";

export function QueuePage() {
  const initial = useLoaderData<PendingAction[]>();
  const source = useDataSource();
  const [state, setState] = useState<QueueState>({ actions: initial });

  // Stay in sync with WhatsApp: apply every real-time change to the queue.
  useEffect(() => source.subscribeToQueue((event) => setState((s) => applyQueueEvent(s, event))), [source]);

  const sorted = [...state.actions].sort(byExpiry);

  return (
    <section>
      <PageTitle>תור אישורים</PageTitle>
      {/* Summaries sit at the top of the queue screen (docs/04-web-app.md, screen map). */}
      <Link to="/summary" className="mb-4 inline-block text-sm text-blue-700 underline">
        לסיכום היומי
      </Link>
      {state.notice && (
        <p role="status" className="mb-4 rounded-lg bg-green-50 p-2 text-sm text-green-900">
          {state.notice}
        </p>
      )}
      {sorted.length === 0 ? (
        <p className="text-slate-600">אין כרגע פעולות שמחכות לך.</p>
      ) : (
        <ul className="space-y-4">
          {sorted.map((a) => (
            <li key={a.id}>
              <ActionCard action={a} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
