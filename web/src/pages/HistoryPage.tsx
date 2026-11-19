import { useState } from "react";
import { useLoaderData } from "react-router";

import { Empty } from "../components/ui";
import type { HistoryEntry } from "../domain/account";
import type { Channel } from "../domain/actions";
import { channelLabel, historyKindLabel } from "../domain/labels";
import { formatDateTime } from "../lib/time";
import { PageTitle } from "./PageTitle";

// UC-A3: what was done, why, who approved, from which channel and when.
// Filtering runs on the loaded list; date-range and contact filters come with the API.
export function HistoryPage() {
  const entries = useLoaderData<HistoryEntry[]>();
  const [channel, setChannel] = useState<Channel | "all">("all");
  const shown = entries
    .filter((e) => channel === "all" || e.channel === channel)
    .sort((a, b) => Date.parse(b.at) - Date.parse(a.at));

  return (
    <section>
      <PageTitle>היסטוריה</PageTitle>
      <label className="mb-5 flex items-center gap-3 text-sm font-medium">
        ערוץ
        <select
          value={channel}
          onChange={(e) => setChannel(e.target.value as Channel | "all")}
          className="min-h-11 rounded-xl border border-line-strong bg-surface px-3 text-[0.9375rem] font-normal"
        >
          <option value="all">הכל</option>
          {(Object.keys(channelLabel) as Channel[]).map((c) => (
            <option key={c} value={c}>
              {channelLabel[c]}
            </option>
          ))}
        </select>
      </label>

      {shown.length === 0 ? (
        <Empty>עדיין אין פעולות בהיסטוריה.</Empty>
      ) : (
        <ol className="flex flex-col overflow-hidden rounded-[var(--radius-card)] border border-line bg-surface">
          {shown.map((e) => (
            <li key={e.id} className="flex flex-col gap-0.5 border-b border-line-soft p-3.5 last:border-b-0">
              <p dir="auto" className="text-[0.9375rem] font-semibold">
                {e.summary}
              </p>
              <p className="text-[0.8125rem] text-muted">
                {formatDateTime(e.at)} · {historyKindLabel(e.kind)} · {channelLabel[e.channel]}
              </p>
              {(e.decidedBy || e.contactName) && (
                <p className="text-[0.8125rem] text-muted">
                  {e.contactName && <span>איש קשר: {e.contactName}. </span>}
                  {e.decidedBy && <span>אישר: {e.decidedBy}</span>}
                </p>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
