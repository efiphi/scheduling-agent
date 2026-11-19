import { useEffect, useState } from "react";
import { Link, useLoaderData } from "react-router";

import { ActionCard } from "../components/ActionCard";
import { useDataSource } from "../data/context";
import type { AgentQuestion } from "../data/source";
import { byExpiry, type PendingAction } from "../domain/actions";
import { applyQueueEvent, type QueueState } from "../domain/queue";
import { Empty, Notice } from "../components/ui";
import { buttonClass } from "../components/styles";
import { PageTitle } from "./PageTitle";

/** Today's date in Hebrew, e.g. "יום רביעי, 19 בנובמבר", above the screen's title. */
function today(): string {
  return new Intl.DateTimeFormat("he-IL", { weekday: "long", day: "numeric", month: "long", timeZone: "Asia/Jerusalem" }).format(new Date());
}

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
      <PageTitle eyebrow={today()}>תור אישורים</PageTitle>
      {state.notice && <Notice tone="ok">{state.notice}</Notice>}
      {questions.length > 0 && (
        // UC-M7: the agent asks instead of guessing. Plain text only (T19).
        <section aria-label="שאלות מהסוכן" className="mb-5 flex flex-col gap-2">
          {questions.map((q) => (
            <div key={q.id} className="flex items-start gap-3 rounded-2xl border border-warn-line bg-warn-bg p-3.5 text-sm text-warn-ink">
              <p dir="auto" className="flex-1 leading-relaxed">
                {q.question}
              </p>
              <button type="button" onClick={() => void dismiss(q.id)} className="min-h-11 flex-none px-2 font-medium underline-offset-4 hover:underline">
                סגור
              </button>
            </div>
          ))}
        </section>
      )}
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-lg font-bold">מחכות לאישור שלך</h2>
        {/* Summaries sit at the top of the queue screen (docs/04-web-app.md, screen map). */}
        <Link to="/summary" className={`${buttonClass.link} text-sm`}>
          לסיכום היומי
        </Link>
      </div>
      {sorted.length === 0 ? (
        <Empty>אין כרגע פעולות שמחכות לך.</Empty>
      ) : (
        <ul className="flex flex-col gap-3.5">
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
