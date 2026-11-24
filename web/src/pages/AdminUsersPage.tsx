import { useState, type FormEvent } from "react";
import { useLoaderData, useRevalidator } from "react-router";

import { buttonClass } from "../components/styles";
import { Card, Empty, Notice } from "../components/ui";
import { useDataSource } from "../data/context";
import type { Invite, ManagedUser } from "../domain/account";
import { formatDateTime } from "../lib/time";
import { PageTitle } from "./PageTitle";

const inviteStatus: Record<Invite["status"], string> = {
  pending: "ממתינה",
  used: "נוצלה",
  expired: "פגה",
  revoked: "בוטלה",
};

const googleStatus: Record<ManagedUser["google"], string> = {
  connected: "Google מחובר",
  expired: "Google פג",
  disconnected: "Google לא מחובר",
};

const inviteErrors: Record<string, string> = {
  "already a user": "לכתובת הזאת כבר יש משתמש.",
  "not an email address": "זו לא כתובת מייל.",
  "admins only": "רק מנהל יכול להזמין.",
};

// UC-A6, admin only. The admin sees who uses the system and how far their setup got —
// never another user's emails, actions or settings (T13).
export function AdminUsersPage() {
  const { users, invites } = useLoaderData<{ users: ManagedUser[]; invites: Invite[] }>();
  const source = useDataSource();
  const revalidator = useRevalidator();
  const [email, setEmail] = useState("");
  const [link, setLink] = useState<string>();
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string>();

  async function invite(event: FormEvent) {
    event.preventDefault();
    setError(undefined);
    setLink(undefined);
    setCopied(false);
    const made = await source.createInvite(email.trim());
    if (made.ok) {
      setLink(made.link);
      setEmail("");
      await revalidator.revalidate();
    } else {
      setError(inviteErrors[made.reason] ?? "ההזמנה נכשלה. נסו שוב.");
    }
  }

  async function copy(text: string) {
    await navigator.clipboard.writeText(text);
    setCopied(true);
  }

  async function revoke(id: string) {
    await source.revokeInvite(id);
    await revalidator.revalidate();
  }

  return (
    <section>
      <PageTitle eyebrow="הגדרות">ניהול משתמשים</PageTitle>

      <Card title="הזמנת משתמש" subtitle="קישור לפעם אחת, ל-72 שעות, לכתובת המייל שתזין בלבד.">
        {error && <Notice tone="danger">{error}</Notice>}
        <form onSubmit={(e) => void invite(e)} className="flex gap-2">
          <label className="sr-only" htmlFor="invite-email">
            כתובת המייל של המוזמן
          </label>
          <input id="invite-email" type="email" required dir="ltr" value={email} onChange={(e) => setEmail(e.target.value)}
            placeholder="name@gmail.com" className="min-h-12 min-w-0 flex-1 rounded-xl border border-line-strong bg-surface px-3" />
          <button type="submit" className={buttonClass.primary}>
            הזמן
          </button>
        </form>

        {link && (
          <div className="mt-4 flex flex-col gap-3 rounded-2xl bg-accent-tint p-3 text-sm">
            <p className="font-semibold">הקישור מוכן. הוא מוצג רק עכשיו, אז העתק ושלח אותו למוזמן.</p>
            <p dir="ltr" className="rounded-lg bg-surface px-2 py-1.5 font-mono text-xs break-all">
              {link}
            </p>
            <button type="button" onClick={() => void copy(link)} className={buttonClass.secondary}>
              {copied ? "הועתק" : "העתק קישור"}
            </button>
            {/* Two steps code cannot do while Google's app is in testing mode and WhatsApp
                uses Meta's test number (docs/adr/024-invites-and-self-serve-onboarding.md). */}
            <div className="flex flex-col gap-1 text-ink-soft">
              <p className="font-semibold text-ink">לפני שהמוזמן מתחיל, שני צעדים ידניים:</p>
              <p>1. להוסיף את הכתובת כמשתמש בדיקה ב-Google Cloud (OAuth consent screen, Test users). אחרת Google יחסום את ההתחברות.</p>
              <p>2. להוסיף את מספר הווטסאפ שלו כנמען במספר הבדיקה של Meta. אחרת הסוכן לא יוכל לענות לו.</p>
            </div>
          </div>
        )}
      </Card>

      <Card title="הזמנות">
        {invites.length === 0 ? (
          <Empty>עוד לא נשלחו הזמנות.</Empty>
        ) : (
          <ul className="flex flex-col">
            {invites.map((i) => (
              <li key={i.id} className="flex items-center justify-between gap-3 border-b border-line-soft py-3 first:pt-0 last:border-b-0 last:pb-0">
                <div className="min-w-0">
                  <bdi className="block truncate font-medium">{i.email}</bdi>
                  <p className="text-xs text-muted">
                    {inviteStatus[i.status]}
                    {i.status === "pending" && ` · בתוקף עד ${formatDateTime(i.expiresAt)}`}
                  </p>
                </div>
                {i.status === "pending" && (
                  <button type="button" onClick={() => void revoke(i.id)} className={`${buttonClass.danger} min-h-10 px-3 text-sm`}>
                    ביטול
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="משתמשים">
        {users.length === 0 ? (
          <Empty>אין משתמשים להצגה.</Empty>
        ) : (
          <ul className="flex flex-col">
            {users.map((u) => (
              <li key={u.email} className="border-b border-line-soft py-3 first:pt-0 last:border-b-0 last:pb-0">
                <bdi className="block font-medium">{u.email}</bdi>
                <p className="text-xs text-muted">
                  {u.isAdmin ? "מנהל · " : ""}
                  {u.status === "paused" ? "מושהה" : "פעיל"} · {googleStatus[u.google]} · {u.whatsappVerified ? "ווטסאפ מאומת" : "ווטסאפ לא מאומת"}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </section>
  );
}
