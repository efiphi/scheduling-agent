import { PageTitle } from "./PageTitle";

// Sign-in is Google only (OpenID Connect, identity scopes only — ADR-010). No passwords.
export function LoginPage() {
  return (
    <section>
      <PageTitle>סוכן פגישות</PageTitle>
      <p className="mb-6 text-slate-700">כניסה עם חשבון Google. אין סיסמאות במערכת.</p>
      {/* A full page navigation: the API redirects to Google and back (ADR-010). */}
      <a href="/api/auth/google/login" className="inline-block rounded-lg bg-blue-700 px-4 py-2 text-white">
        התחברות עם Google
      </a>
      <p className="mt-6 text-sm text-slate-600">ההצטרפות היא בהזמנה בלבד.</p>
    </section>
  );
}
