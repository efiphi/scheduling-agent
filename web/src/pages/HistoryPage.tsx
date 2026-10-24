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
      <label className="mb-4 flex items-center gap-2 text-sm">
        ערוץ
        <select
          value={channel}
          onChange={(e) => setChannel(e.target.value as Channel | "all")}
          className="rounded-lg border border-slate-300 bg-white px-2 py-1"
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
        <ol className="space-y-3">
          {shown.map((e) => (
            <li key={e.id} className="rounded-xl border border-slate-200 bg-white p-3">
              <p className="text-sm text-slate-600">
                {formatDateTime(e.at)} · {historyKindLabel(e.kind)} · {channelLabel[e.channel]}
              </p>
              <p dir="auto">{e.summary}</p>
              {(e.decidedBy || e.contactName) && (
                <p className="text-sm text-slate-600">
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
