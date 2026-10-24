import { useLoaderData } from "react-router";

import { Card, Field, PendingButton } from "../components/ui";
import type { Account, ConnectionStatus } from "../domain/account";
import { PageTitle } from "./PageTitle";

const connectionLabel: Record<ConnectionStatus, string> = {
  connected: "מחובר",
  expired: "פג — צריך לחבר מחדש",
  disconnected: "לא מחובר",
};

// docs/04-web-app.md, "security". Everything here changes how the agent can be controlled,
// so changes require re-authentication with Google (and extra verification where noted).
export function SecurityPage() {
  const account = useLoaderData<Account | null>();

  return (
    <section>
      <PageTitle>אבטחה</PageTitle>

      <Card title="השהיית הסוכן">
        {/* ADR-014: same effect as the stop code, from any browser after a normal login. */}
        <p className="mb-3 text-sm text-slate-700">
          הסוכן יפסיק לפעול וכל הפעולות הממתינות יבוטלו. אותה השפעה כמו קוד העצירה. חזרה לפעולה דורשת התחברות מחדש.
        </p>
        <PendingButton tone="danger">השהה סוכן</PendingButton>
      </Card>

      <Card title="עצירת חירום">
        <p className="mb-2 text-sm text-slate-700">
          קוד העצירה מתקבל רק מהמספר שלך או ממספר גיבוי שהגדרת מראש.
        </p>
        <dl>
          <Field label="קוד עצירה" hint="לא מוצג אחרי השמירה">
            {account && "מוגדר"}
          </Field>
          <Field label="מספרי גיבוי">
            {account && account.backupNumbers.length > 0 && (
              <ul>
                {account.backupNumbers.map((n) => (
                  <li key={n}>
                    <bdi>{n}</bdi>
                  </li>
                ))}
              </ul>
            )}
          </Field>
        </dl>
        <p className="mt-2 text-xs text-slate-500">שינוי דורש התחברות מחדש ואימות נוסף.</p>
        <div className="mt-2">
          <PendingButton>שינוי קוד או מספרים</PendingButton>
        </div>
      </Card>

      <Card title="אימות לבקשות חריגות">
        <dl>
          <Field label="אמצעי אימות">
            {account?.verificationMethod &&
              (account.verificationMethod === "pin" ? "קוד אישי (PIN)" : "שאלה סודית")}
          </Field>
        </dl>
        <div className="mt-2">
          <PendingButton>שינוי</PendingButton>
        </div>
      </Card>

      <Card title="חשבונות מחוברים">
        <dl>
          <Field label="Google">{account && connectionLabel[account.google]}</Field>
          <Field label="ווטסאפ">{account?.whatsappNumber && <bdi>{account.whatsappNumber}</bdi>}</Field>
        </dl>
      </Card>

      <Card title="סשנים פעילים">
        <PendingButton>ניתוק כל הסשנים</PendingButton>
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
