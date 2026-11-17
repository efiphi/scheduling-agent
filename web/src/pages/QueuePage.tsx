import { useEffect, useState } from "react";
import { Link, useLoaderData } from "react-router";

import { ActionCard } from "../components/ActionCard";
import { useDataSource } from "../data/context";
import type { AgentQuestion } from "../data/source";
import { byExpiry, type PendingAction } from "../domain/actions";
import { applyQueueEvent, type QueueState } from "../domain/queue";
import { PageTitle } from "./PageTitle";

export function QueuePage() {
  const initial = useLoaderData<PendingAction[]>();
  const source = useDataSource();
  const [state, setState] = useState<QueueState>({ actions: initial });
  const [questions, setQuestions] = useState<AgentQuestion[]>([]);

  // Stay in sync with WhatsApp: apply every real-time change to the queue.
  useEffect(() => source.subscribeToQueue((event) => setState((s) => applyQueueEvent(s, event))), [source]);
  useEffect(() => {
    void source.listQuestions().then(setQuestions, () => undefined);
  }, [source]);

  function decided(id: string, decision: "approved" | "rejected") {
    setState((s) => applyQueueEvent(s, { type: "decided", id, decision, channel: "web" }));
  }

  async function dismiss(id: string) {
    const result = await source.dismissQuestion(id);
    if (result.ok) setQuestions((qs) => qs.filter((q) => q.id !== id));
  }

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
      {questions.length > 0 && (
        // UC-M7: the agent asks instead of guessing. Plain text only (T19).
        <section aria-label="שאלות מהסוכן" className="mb-4 space-y-2">
          {questions.map((q) => (
            <div key={q.id} className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm">
              <p dir="auto" className="mb-2 text-amber-950">
                {q.question}
              </p>
              <button type="button" onClick={() => void dismiss(q.id)} className="text-amber-900 underline">
                סגור
              </button>
            </div>
          ))}
        </section>
      )}
      {sorted.length === 0 ? (
        <p className="text-slate-600">אין כרגע פעולות שמחכות לך.</p>
      ) : (
        <ul className="space-y-4">
          {sorted.map((a) => (
            <li key={a.id}>
              <ActionCard action={a} onDecided={decided} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
