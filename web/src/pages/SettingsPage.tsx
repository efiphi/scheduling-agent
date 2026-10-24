import type { ReactNode } from "react";
import { Link, useLoaderData } from "react-router";

import { Card, Field, PendingButton } from "../components/ui";
import type { Settings, Tracked } from "../domain/account";
import { channelLabel } from "../domain/labels";
import { formatDateTime } from "../lib/time";
import { PageTitle } from "./PageTitle";

// UC-A5: every setting from the use-cases table, with when it last changed and from which channel.
// Settings change only from the verified owner (invariant 9); editing is wired in Layer 1.
const rows: { key: keyof Settings; label: string; format?: (v: never) => ReactNode }[] = [
  { key: "workDays", label: "ימי עבודה" },
  { key: "workHours", label: "שעות עבודה" },
  { key: "endOfWorkday", label: "שעת סיום יום העבודה" },
  { key: "bufferMinutes", label: "זמן מעבר בין פגישות", format: (v: number) => `${v} דקות` },
  { key: "maxMeetingsPerDay", label: "מקסימום פגישות ביום" },
  { key: "defaultDurationMinutes", label: "משך ברירת מחדל", format: (v: number) => `${v} דקות` },
  { key: "blockedTimes", label: "ימים וזמנים חסומים", format: (v: string[]) => v.join(", ") || "אין" },
  { key: "meetingType", label: "סוג פגישה ברירת מחדל" },
  { key: "replyLanguage", label: "שפת תשובה" },
  { key: "timeZone", label: "אזור זמן", format: (v: string) => <bdi>{v}</bdi> },
];

function changedHint(t: Tracked<unknown>): string | undefined {
  if (!t.changedAt) return undefined;
  return `שונה ${formatDateTime(t.changedAt)}${t.changedVia ? ` · ${channelLabel[t.changedVia]}` : ""}`;
}

export function SettingsPage() {
  const settings = useLoaderData<Settings | null>();

  return (
    <section>
      <PageTitle>הגדרות</PageTitle>
      <Card title="העדפות תיאום">
        <dl>
          {rows.map(({ key, label, format }) => {
            const tracked = settings?.[key];
            const value = tracked ? (format ? format(tracked.value as never) : String(tracked.value)) : undefined;
            return (
              <Field key={key} label={label} hint={tracked && changedHint(tracked)}>
                {value}
              </Field>
            );
          })}
        </dl>
        <div className="mt-3">
          <PendingButton>עריכה</PendingButton>
        </div>
      </Card>

      <Link to="/settings/security" className="block rounded-xl border border-slate-200 bg-white p-4 font-semibold text-blue-700">
        אבטחה: השהיית הסוכן, קוד עצירה, חשבונות מחוברים ←
      </Link>
    </section>
  );
}
