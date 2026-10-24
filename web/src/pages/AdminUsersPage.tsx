import { useLoaderData } from "react-router";

import { Card, Empty, PendingButton } from "../components/ui";
import type { ManagedUser } from "../domain/account";
import { PageTitle } from "./PageTitle";

const statusLabel: Record<ManagedUser["status"], string> = {
  invited: "הוזמן",
  active: "פעיל",
  removed: "הוסר",
};

// UC-A6, admin only. The admin sees names and status — never another user's data (T13).
export function AdminUsersPage() {
  const users = useLoaderData<ManagedUser[]>();

  return (
    <section>
      <PageTitle>ניהול משתמשים</PageTitle>
      <Card title="הזמנת משתמש">
        <p className="mb-3 text-sm text-slate-700">ההזמנה חד-פעמית, עם תוקף, וקשורה לכתובת המייל שתזין (T14).</p>
        <PendingButton tone="primary">שליחת הזמנה</PendingButton>
      </Card>
      <Card title="משתמשים">
        {users.length === 0 ? (
          <Empty>אין משתמשים להצגה.</Empty>
        ) : (
          <ul className="space-y-2">
            {users.map((u) => (
              <li key={u.email} className="flex items-center justify-between gap-2">
                <span>
                  <bdi>{u.email}</bdi> · {statusLabel[u.status]}
                </span>
                <PendingButton tone="danger">{u.status === "invited" ? "ביטול הזמנה" : "הסרה"}</PendingButton>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </section>
  );
}
