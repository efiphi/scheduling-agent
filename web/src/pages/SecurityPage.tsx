import { useEffect, useState, type FormEvent } from "react";

import { Card, Field, PendingButton } from "../components/ui";
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
      <PageTitle>אבטחה</PageTitle>

      {message && (
        <p role="status" className="mb-4 rounded-lg bg-green-50 p-2 text-sm text-green-900">
          {message}
        </p>
      )}
      {needsLogin && (
        <p role="alert" className="mb-4 rounded-lg bg-amber-50 p-2 text-sm text-amber-900">
          פעולה רגישה: צריך להתחבר שוב עם Google.{" "}
          <a href={LOGIN_URL} className="underline">
            להתחברות
          </a>
        </p>
      )}

      <Card title={paused ? "הסוכן מושהה" : "השהיית הסוכן"}>
        {paused ? (
          <>
            <p className="mb-3 text-sm text-slate-700">הסוכן לא פועל. חזרה לפעולה דורשת התחברות מחדש.</p>
            <button type="button" onClick={() => void act(() => source.resumeAgent(), "הסוכן חזר לפעול.")} className="rounded-lg bg-blue-700 px-4 py-2 text-white">
              החזר לפעולה
            </button>
          </>
        ) : (
          <>
            {/* ADR-014: same effect as the stop code, from any browser after a normal login. */}
            <p className="mb-3 text-sm text-slate-700">
              הסוכן יפסיק לפעול וכל הפעולות הממתינות יבוטלו. אותה השפעה כמו קוד העצירה. חזרה לפעולה דורשת התחברות מחדש.
            </p>
            <button type="button" onClick={() => void act(() => source.pauseAgent(), "הסוכן הושהה.")} className="rounded-lg border border-red-300 px-4 py-2 text-red-800">
              השהה סוכן
            </button>
          </>
        )}
      </Card>

      <Card title="ווטסאפ">
        {status?.whatsappVerified ? (
          <p className="text-sm text-slate-700">המספר שלך מאומת.</p>
        ) : verification ? (
          // ADR-017: the user sends the code from their phone, which proves the number.
          <p className="text-sm text-slate-700">
            שלח מהווטסאפ שלך את ההודעה <bdi className="font-mono font-semibold">אימות {verification.code}</bdi> למספר{" "}
            <bdi className="font-semibold">{verification.agentNumber}</bdi>. הקוד תקף ל-10 דקות ולפעם אחת.
          </p>
        ) : (
          <>
            <p className="mb-3 text-sm text-slate-700">כדי לדבר עם הסוכן בווטסאפ, צריך לאמת את המספר שלך פעם אחת.</p>
            <button type="button" onClick={() => void source.startWhatsAppVerification().then(setVerification)} className="rounded-lg bg-blue-700 px-4 py-2 text-white">
              קבל קוד אימות
            </button>
          </>
        )}
      </Card>

      <Card title="עצירת חירום">
        <p className="mb-2 text-sm text-slate-700">
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
            className="flex-1 rounded-lg border border-slate-300 px-2 py-1" />
          <button type="submit" className="rounded-lg border border-slate-300 px-3">שמור</button>
        </form>
        <form onSubmit={(e) => void saveBackups(e)} className="mt-2 flex gap-2">
          <label className="sr-only" htmlFor="backups">
            מספרי גיבוי
          </label>
          <input id="backups" inputMode="tel" value={backups} onChange={(e) => setBackups(e.target.value)}
            placeholder="עד שני מספרים, למשל 972501234567" dir="ltr"
            className="flex-1 rounded-lg border border-slate-300 px-2 py-1" />
          <button type="submit" className="rounded-lg border border-slate-300 px-3">שמור</button>
        </form>
        <p className="mt-2 text-xs text-slate-500">שינוי דורש התחברות מחדש ב-10 הדקות האחרונות.</p>
      </Card>

      <Card title="סשנים פעילים">
        <button type="button" onClick={() => void act(() => source.logOutEverywhere(), "כל הסשנים נותקו.")} className="rounded-lg border border-slate-300 px-4 py-2">
          ניתוק כל הסשנים
        </button>
      </Card>

      <Card title="ניתוק ומחיקה">
        <p className="mb-3 text-sm text-slate-700">
          מחיקה מלאה של כל הנתונים והטוקנים. ביומן הפעולות נשארות רק רשומות אנונימיות.
        </p>
        <PendingButton tone="danger">מחיקת החשבון</PendingButton>
      </Card>
    </section>
  );
}
