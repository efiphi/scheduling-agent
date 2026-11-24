import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useLoaderData, useLocation, useRevalidator } from "react-router";

import { GoogleConnectButton, GoogleScopes } from "../components/GoogleConnect";
import { buttonClass } from "../components/styles";
import { Icon, Notice } from "../components/ui";
import { useDataSource } from "../data/context";
import type { WhatsAppVerification } from "../data/source";
import type { Account } from "../domain/account";
import { googleOutcome } from "../lib/google";
import { PageTitle } from "./PageTitle";

// docs/04-web-app.md, "onboarding" (UC-A1): a short wizard that can be left and resumed.
// Every step reads its state from the api, so coming back later shows what is already done.
// Not here yet: working hours (defaults 09:00-18:00 until settings can be edited) and the
// PIN for unusual requests, which the api does not have yet.
export function OnboardingPage() {
  const account = useLoaderData<Account | null>();
  const location = useLocation();
  const [index, setIndex] = useState(0);
  const outcome = googleOutcome(location.search);

  const steps: { title: string; done: boolean; body: ReactNode }[] = [
    {
      title: "חיבור המייל והיומן",
      done: account?.google === "connected",
      body: (
        <>
          {outcome && <Notice tone={outcome.tone}>{outcome.text}</Notice>}
          <p className="mb-3">הסוכן צריך גישה ל-Gmail וליומן. לפני ההפניה ל-Google, אלה ההרשאות ולמה:</p>
          <GoogleScopes />
          <div className="mt-4">
            <GoogleConnectButton status={account?.google ?? "disconnected"} returnTo="onboarding" />
          </div>
        </>
      ),
    },
    {
      title: "אימות מספר הווטסאפ",
      done: account?.whatsappVerified ?? false,
      body: <WhatsAppStep verified={account?.whatsappVerified ?? false} />,
    },
    {
      title: "קוד עצירת חירום",
      done: false,
      body: <StopCodeStep />,
    },
    {
      title: "מוכן",
      done: false,
      body: (
        <div className="flex flex-col gap-3">
          <p>
            מעכשיו הסוכן קורא את המייל פעם בדקה. כשמגיעה בקשה לפגישה, הוא מציע מועדים מהיומן ושולח לך כרטיס לאישור, כאן ובווטסאפ.
            שום דבר לא נשלח בלי האישור שלך.
          </p>
          <Link to="/" className={buttonClass.primary}>
            לתור האישורים
          </Link>
        </div>
      ),
    },
  ];

  const step = steps[index] ?? steps[0];
  const isLast = index === steps.length - 1;

  return (
    <section className="pt-6">
      <PageTitle eyebrow={`שלב ${index + 1} מתוך ${steps.length}`}>הגדרה ראשונית</PageTitle>

      <ol aria-label="שלבים" className="mb-5 flex gap-1.5">
        {steps.map((s, i) => (
          <li key={s.title} className={`h-1.5 flex-1 rounded-full ${i <= index || s.done ? "bg-accent" : "bg-line"}`}>
            <span className="sr-only">
              {s.title}
              {s.done ? " (הושלם)" : ""}
            </span>
          </li>
        ))}
      </ol>

      <div className="mb-6 rounded-[var(--radius-card)] border border-line bg-surface p-4" aria-live="polite">
        <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
          {step?.title}
          {step?.done && (
            <span className="inline-flex items-center gap-1 rounded-md bg-ok-bg px-1.5 py-0.5 text-xs font-semibold text-ok">
              <Icon name="check" className="size-3.5" />
              הושלם
            </span>
          )}
        </h2>
        <div className="text-ink-soft">{step?.body}</div>
      </div>

      {!isLast && (
        <div className="flex justify-between">
          <button type="button" onClick={() => setIndex((i) => i - 1)} disabled={index === 0} className={buttonClass.secondary}>
            הקודם
          </button>
          <button type="button" onClick={() => setIndex((i) => i + 1)} className={buttonClass.primary}>
            {step?.done ? "הבא" : "דלג בינתיים"}
          </button>
        </div>
      )}
    </section>
  );
}

// ADR-017: the user sends the code from their phone, which proves the number is theirs.
function WhatsAppStep({ verified }: { verified: boolean }) {
  const source = useDataSource();
  const revalidator = useRevalidator();
  const [verification, setVerification] = useState<WhatsAppVerification | null>(null);

  if (verified) return <p>המספר שלך מאומת. מעכשיו אפשר לדבר עם הסוכן בווטסאפ.</p>;

  return (
    <div className="flex flex-col gap-3">
      <p>כדי לדבר עם הסוכן ולקבל ממנו כרטיסי אישור בווטסאפ, מאמתים את המספר פעם אחת.</p>
      {verification ? (
        <>
          <p>
            שלח מהווטסאפ שלך את ההודעה <bdi className="font-mono font-semibold text-ink">אימות {verification.code}</bdi> למספר{" "}
            <bdi className="font-semibold text-ink">{verification.agentNumber}</bdi>. הקוד תקף ל-10 דקות ולפעם אחת.
          </p>
          <p className="text-sm text-muted">אם לא מגיעה תשובה, בקשו ממי שהזמין אתכם לוודא שהמספר רשום אצל הסוכן.</p>
          <button type="button" onClick={() => void revalidator.revalidate()} className={buttonClass.secondary}>
            שלחתי, לבדוק שוב
          </button>
        </>
      ) : (
        <button type="button" onClick={() => void source.startWhatsAppVerification().then(setVerification)} className={buttonClass.primary}>
          קבל קוד אימות
        </button>
      )}
    </div>
  );
}

// ADR-014: the stop code pauses the agent from the verified number or a backup number.
function StopCodeStep() {
  const source = useDataSource();
  const [code, setCode] = useState("");
  const [result, setResult] = useState<"saved" | "login" | "failed">();

  async function save(event: FormEvent) {
    event.preventDefault();
    const done = await source.setStopCode(code);
    setCode("");
    setResult(done.ok ? "saved" : done.reason === "login again" ? "login" : "failed");
  }

  return (
    <div className="flex flex-col gap-3">
      <p>
        מילה או משפט שרק אתה יודע. אם משהו נראה לא בסדר, שולחים אותו לסוכן בווטסאפ והוא נעצר מיד ומבטל כל פעולה ממתינה. אפשר להגדיר
        גם מספרי גיבוי במסך האבטחה.
      </p>
      {result === "saved" && <Notice tone="ok">קוד העצירה נשמר. הוא לא יוצג שוב.</Notice>}
      {result === "login" && (
        <Notice tone="warn">
          פעולה רגישה: צריך להתחבר שוב עם Google.{" "}
          <a href="/api/auth/google/login" className="underline">
            להתחברות
          </a>
        </Notice>
      )}
      {result === "failed" && <Notice tone="danger">השמירה נכשלה. נסו שוב.</Notice>}
      <form onSubmit={(e) => void save(e)} className="flex gap-2">
        <label className="sr-only" htmlFor="onboarding-stop-code">
          קוד עצירה
        </label>
        <input id="onboarding-stop-code" type="password" autoComplete="new-password" minLength={6} required value={code}
          onChange={(e) => setCode(e.target.value)} placeholder="6 תווים לפחות"
          className="min-h-12 flex-1 rounded-xl border border-line-strong bg-surface px-3" />
        <button type="submit" className={buttonClass.secondary}>
          שמור
        </button>
      </form>
    </div>
  );
}
