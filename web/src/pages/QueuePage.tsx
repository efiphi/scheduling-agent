import { useLoaderData } from "react-router";

import { ActionCard } from "../components/ActionCard";
import { byExpiry, type PendingAction } from "../domain/actions";
import { PageTitle } from "./PageTitle";

export function QueuePage() {
  const actions = useLoaderData<PendingAction[]>();
  const sorted = [...actions].sort(byExpiry);

  return (
    <section>
      <PageTitle>תור אישורים</PageTitle>
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
