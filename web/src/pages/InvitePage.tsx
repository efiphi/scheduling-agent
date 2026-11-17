import { Link } from "react-router";

import { PageTitle } from "./PageTitle";

// /invite/:token — a single-use, expiring invite bound to one email address (T14).
// Until the API can check the token, every invite is treated as not found.
export function InvitePage() {
  return (
    <section>
      <PageTitle>הזמנה</PageTitle>
      <p className="mb-4 text-slate-700">ההזמנה לא נמצאה, פגה או כבר נוצלה.</p>
      <p className="mb-6 text-sm text-slate-600">
        כל הזמנה מיועדת לכתובת מייל אחת. התחברות עם חשבון אחר נדחית.
      </p>
      <Link to="/login" className="text-blue-700 underline">
        למסך ההתחברות
      </Link>
    </section>
  );
}
