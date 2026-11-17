import { useLoaderData } from "react-router";

import { Card, Empty, PendingButton } from "../components/ui";
import type { DailySummary } from "../domain/account";
import { formatDateTime } from "../lib/time";
import { PageTitle } from "./PageTitle";

// UC-A4 and UC-M8: the daily summary, including what the rule-based filter skipped (E9).
export function SummaryPage() {
  const summary = useLoaderData<DailySummary | null>();

  return (
    <section>
      <PageTitle>סיכום יומי</PageTitle>
      {!summary ? (
        <Empty>אין עדיין נתונים לסיכום.</Empty>
      ) : (
        <>
          <Card title="במבט אחד">
            <dl className="grid grid-cols-3 gap-2 text-center">
              <Stat label="פגישות השבוע" value={summary.meetingsThisWeek} />
              <Stat label="ממתינות לצד השני" value={summary.awaitingReply} />
              <Stat label="פגו אתמול" value={summary.expiredYesterday} />
            </dl>
          </Card>

          <Card title="מיילים שהסוכן דילג עליהם">
            <p className="mb-2 text-sm text-slate-600">שולח, נושא וזמן בלבד, מ-7 הימים האחרונים.</p>
            {summary.skippedEmails.length === 0 ? (
              <Empty>הסוכן לא דילג על מיילים.</Empty>
            ) : (
              <ul className="space-y-2">
                {summary.skippedEmails.map((m) => (
                  <li key={m.id} className="flex items-center justify-between gap-2 border-b border-slate-100 pb-2 last:border-b-0">
                    <div className="min-w-0">
                      {/* T19: sender and subject come from outside and stay plain text. */}
                      <p className="truncate" dir="auto">
                        {m.subject}
                      </p>
                      <p className="text-sm text-slate-600">
                        <bdi>{m.from}</bdi> · {formatDateTime(m.receivedAt)}
                      </p>
                    </div>
                    <PendingButton>זו הייתה בקשה לפגישה</PendingButton>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    // Label first in the markup (valid <dl>), number shown on top.
    <div className="flex flex-col-reverse">
      <dt className="text-xs text-slate-600">{label}</dt>
      <dd className="text-2xl font-bold">{value}</dd>
    </div>
  );
}
