import { PendingButton } from "../components/ui";
import { PageTitle } from "./PageTitle";

// Sign-in is Google only (OpenID Connect, identity scopes only — ADR-010). No passwords.
export function LoginPage() {
  return (
    <section>
      <PageTitle>סוכן פגישות</PageTitle>
      <p className="mb-6 text-slate-700">כניסה עם חשבון Google. אין סיסמאות במערכת.</p>
      <PendingButton tone="primary">התחברות עם Google</PendingButton>
      <p className="mt-6 text-sm text-slate-600">ההצטרפות היא בהזמנה בלבד.</p>
    </section>
  );
}
