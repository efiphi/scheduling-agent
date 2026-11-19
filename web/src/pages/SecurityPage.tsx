import { useEffect, useState, type FormEvent } from "react";

import { Card, Field, Icon, Notice, PendingButton } from "../components/ui";
import { buttonClass } from "../components/styles";
import { useDataSource } from "../data/context";
import type { DecisionResult, SecurityStatus, WhatsAppVerification } from "../data/source";
import { PageTitle } from "./PageTitle";

const LOGIN_URL = "/api/auth/google/login";

// docs/04-web-app.md, "security"; ADR-014, ADR-017. Changing the stop code or backup numbers,
// and resuming the agent, need a fresh Google login: a live session alone is not enough.
export function SecurityPage() {
  const source = useDataSource();
  const [status, setStatus] = useState<SecurityStatus | null>(null);
  const [message, setMessage] = useState<string>();
  const [needsLogin, setNeedsLogin] = useState(false);
  const [verification, setVerification] = useState<WhatsAppVerification | null>(null);
  const [stopCode, setStopCode] = useState("");
  const [backups, setBackups] = useState("");

  async function refresh() {
    setStatus(await source.getSecurity());
  }

  useEffect(() => {
    void source.getSecurity().then(setStatus, () => undefined);
  }, [source]);

  async function act(action: () => Promise<DecisionResult>, done: string) {
    setMessage(undefined);
    setNeedsLogin(false);
    const result = await action();
    if (result.ok) {
      setMessage(done);
      await refresh();
    } else if (result.reason === "login again") {
      setNeedsLogin(true);
    } else {
      setMessage("הפעולה נכשלה. בדוק את הפרטים ונסה שוב.");
    }
  }

  async function saveStopCode(event: FormEvent) {
    event.preventDefault();
    await act(() => source.setStopCode(stopCode), "קוד העצירה נשמר.");
    setStopCode("");
  }

  async function saveBackups(event: FormEvent) {
    event.preventDefault();
    const numbers = backups.split(/[,\n]/).map((n) => n.trim()).filter(Boolean);
    await act(() => source.setBackupNumbers(numbers), "מספרי הגיבוי נשמרו.");
    setBackups("");
  }

  const paused = status?.agentStatus === "paused";

  return (
    <section>
      <PageTitle eyebrow="הגדרות">אבטחה</PageTitle>

      {message && <Notice tone="ok">{message}</Notice>}
      {needsLogin && (
        <p role="alert" className="mb-4 rounded-xl bg-warn-bg px-3 py-2.5 text-sm text-warn-ink">
          פעולה רגישה: צריך להתחבר שוב עם Google.{" "}
          <a href={LOGIN_URL} className="underline">
            להתחברות
          </a>
        </p>
      )}

      <section aria-labelledby="agent-state" className="mb-3.5 flex flex-col gap-3 rounded-[var(--radius-card)] border border-line bg-surface p-[1.125rem]">
        <div className="flex items-center gap-3">
          <span className={`flex size-11 flex-none items-center justify-center rounded-2xl ${paused ? "bg-danger-bg text-danger" : "bg-ok-bg text-ok"}`}>
            <Icon name={paused ? "pause" : "shield"} className="size-[22px]" />
          </span>
          <div>
            <h2 id="agent-state" className="text-[1.0625rem] font-semibold">
              {paused ? "הסוכן מושהה" : "השהיית הסוכן"}
            </h2>
            <p className="text-[0.8125rem] text-muted">{paused ? "לא קורא מיילים ולא שולח דבר" : "הסוכן פעיל וקורא מיילים"}</p>
          </div>
        </div>
        {paused ? (
          <>
            <p className="text-sm leading-relaxed text-ink-soft">הסוכן לא פועל. חזרה לפעולה דורשת התחברות מחדש.</p>
            <button type="button" onClick={() => void act(() => source.resumeAgent(), "הסוכן חזר לפעול.")} className={buttonClass.primary}>
              החזר לפעולה
            </button>
          </>
        ) : (
          <>
            {/* ADR-014: same effect as the stop code, from any browser after a normal login. */}
            <p className="text-sm leading-relaxed text-ink-soft">
              הסוכן יפסיק לפעול וכל הפעולות הממתינות יבוטלו. אותה השפעה כמו קוד העצירה. חזרה לפעולה דורשת התחברות מחדש.
            </p>
            <button type="button" onClick={() => void act(() => source.pauseAgent(), "הסוכן הושהה.")} className={buttonClass.dangerStrong}>
              <Icon name="pause" className="size-[18px]" />
              השהה סוכן
            </button>
          </>
        )}
      </section>

      <Card title="ווטסאפ">
        {status?.whatsappVerified ? (
          <p className="text-sm text-ink-soft">המספר שלך מאומת.</p>
        ) : verification ? (
          // ADR-017: the user sends the code from their phone, which proves the number.
          <p className="text-sm text-ink-soft">
            שלח מהווטסאפ שלך את ההודעה <bdi className="font-mono font-semibold">אימות {verification.code}</bdi> למספר{" "}
            <bdi className="font-semibold">{verification.agentNumber}</bdi>. הקוד תקף ל-10 דקות ולפעם אחת.
          </p>
        ) : (
          <>
            <p className="mb-3 text-sm text-ink-soft">כדי לדבר עם הסוכן בווטסאפ, צריך לאמת את המספר שלך פעם אחת.</p>
            <button type="button" onClick={() => void source.startWhatsAppVerification().then(setVerification)} className="min-h-11 rounded-2xl bg-accent px-5 font-semibold text-white hover:bg-accent-hover">
              קבל קוד אימות
            </button>
          </>
        )}
      </Card>

      <Card title="עצירת חירום">
        <p className="mb-2 text-sm text-ink-soft">
          קוד העצירה מתקבל רק מהמספר שלך או ממספר גיבוי שהגדרת מראש. הוא משהה את הסוכן ומבטל כל פעולה ממתינה.
        </p>
        <dl>
          <Field label="קוד עצירה" hint="לא מוצג אחרי השמירה">
            {status && (status.stopCodeSet ? "מוגדר" : "לא מוגדר")}
          </Field>
          <Field label="מספרי גיבוי">
            {status && status.backupNumbers.length > 0 && (
              <ul>
                {status.backupNumbers.map((n) => (
                  <li key={n}>
                    <bdi>{n}</bdi>
                  </li>
                ))}
              </ul>
            )}
          </Field>
        </dl>
        <form onSubmit={(e) => void saveStopCode(e)} className="mt-3 flex gap-2">
          <label className="sr-only" htmlFor="stop-code">
            קוד עצירה חדש
          </label>
          <input id="stop-code" type="password" autoComplete="new-password" minLength={6} required value={stopCode}
            onChange={(e) => setStopCode(e.target.value)} placeholder="קוד עצירה חדש (6 תווים לפחות)"
            className="min-h-11 flex-1 rounded-xl border border-line-strong bg-surface px-3" />
          <button type="submit" className="min-h-11 rounded-xl border border-line-strong bg-surface px-4 font-medium hover:bg-sunken">שמור</button>
        </form>
        <form onSubmit={(e) => void saveBackups(e)} className="mt-2 flex gap-2">
          <label className="sr-only" htmlFor="backups">
            מספרי גיבוי
          </label>
          <input id="backups" inputMode="tel" value={backups} onChange={(e) => setBackups(e.target.value)}
            placeholder="עד שני מספרים, למשל 972501234567" dir="ltr"
            className="min-h-11 flex-1 rounded-xl border border-line-strong bg-surface px-3" />
          <button type="submit" className="min-h-11 rounded-xl border border-line-strong bg-surface px-4 font-medium hover:bg-sunken">שמור</button>
        </form>
        <p className="mt-2 text-xs text-muted">שינוי דורש התחברות מחדש ב-10 הדקות האחרונות.</p>
      </Card>

      <Card title="סשנים פעילים">
        <button type="button" onClick={() => void act(() => source.logOutEverywhere(), "כל הסשנים נותקו.")} className="min-h-11 rounded-2xl border border-line-strong bg-surface px-5 font-medium hover:bg-sunken">
          ניתוק כל הסשנים
        </button>
      </Card>

      <Card title="ניתוק ומחיקה">
        <p className="mb-3 text-sm text-ink-soft">
          מחיקה מלאה של כל הנתונים והטוקנים. ביומן הפעולות נשארות רק רשומות אנונימיות.
        </p>
        <PendingButton tone="danger">מחיקת החשבון</PendingButton>
      </Card>
    </section>
  );
}
