import { useSearchParams } from "react-router";

import { Icon, Notice, type IconName } from "../components/ui";
import { buttonClass } from "../components/styles";

// The api sends refused logins back here with a short code; only known codes are shown (T19).
const errors: Record<string, string> = {
  not_invited: "החשבון הזה לא מוזמן למערכת. ההצטרפות היא דרך קישור הזמנה, עם החשבון שאליו נשלחה.",
  failed: "ההתחברות לא הושלמה. נסו שוב.",
};

const promises: readonly { icon: IconName; text: string }[] = [
  { icon: "check", text: "כל שליחה מחכה לאישור שלך" },
  { icon: "shield", text: "אין לו הרשאה למחוק מיילים" },
  { icon: "pause", text: "אפשר לעצור אותו בכל רגע" },
];

// Sign-in is Google only (OpenID Connect, identity scopes only — ADR-010). No passwords.
export function LoginPage() {
  const [params] = useSearchParams();
  const error = errors[params.get("error") ?? ""];

  return (
    <section className="flex min-h-[calc(100dvh-5rem)] flex-col justify-between gap-10 pt-10">
      <div className="flex flex-col gap-7">
        <span className="flex size-16 items-center justify-center rounded-[1.25rem] bg-accent text-white">
          <Icon name="calendar" className="size-8" />
        </span>
        <div className="flex flex-col gap-2.5">
          <h1 className="text-[2.125rem] leading-tight font-bold tracking-tight">סוכן פגישות</h1>
          <p className="text-[1.0625rem] leading-relaxed text-ink-soft">
            קורא את המייל, מציע מועדים מהיומן שלך, ופועל רק אחרי שאישרת. כניסה עם חשבון Google. אין סיסמאות במערכת.
          </p>
        </div>
        <ul className="flex flex-col gap-3.5">
          {promises.map((p) => (
            <li key={p.text} className="flex items-center gap-3 text-[0.9375rem]">
              <span className="flex size-8 flex-none items-center justify-center rounded-[0.625rem] bg-accent-soft text-accent">
                <Icon name={p.icon} className="size-4" />
              </span>
              {p.text}
            </li>
          ))}
        </ul>
      </div>
      <div className="flex flex-col gap-3.5">
        {error && <Notice tone="danger">{error}</Notice>}
        {/* A full page navigation: the API redirects to Google and back (ADR-010). */}
        <a href="/api/auth/google/login" className={`${buttonClass.secondary} min-h-14 shadow-sm`}>
          התחברות עם Google
        </a>
        <p className="text-center text-[0.8125rem] leading-relaxed text-muted">
          ההצטרפות היא בהזמנה בלבד. ההתחברות מבקשת רק את הזהות שלך, בלי גישה למייל.
        </p>
      </div>
    </section>
  );
}
