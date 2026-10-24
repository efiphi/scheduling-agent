import { useState } from "react";
import { useLoaderData } from "react-router";

import { Empty, PendingButton } from "../components/ui";
import type { Contact } from "../domain/account";
import { PageTitle } from "./PageTitle";

// UC-A8: unique name and email for every contact the agent knows.
// Contacts still waiting for a name are listed first (UC-M9).
export function ContactsPage() {
  const contacts = useLoaderData<Contact[]>();
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const shown = contacts
    .filter((c) => !q || c.email.toLowerCase().includes(q) || (c.name ?? "").toLowerCase().includes(q))
    .sort((a, b) => Number(Boolean(a.name)) - Number(Boolean(b.name)));

  return (
    <section>
      <PageTitle>אנשי קשר</PageTitle>
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="חיפוש לפי שם או מייל"
        aria-label="חיפוש אנשי קשר"
        className="mb-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2"
      />
      {/* T29: changing an existing contact's address is an unusual request. */}
      <p className="mb-4 text-sm text-slate-600">שינוי כתובת של איש קשר קיים דורש אימות נוסף.</p>

      {shown.length === 0 ? (
        <Empty>{contacts.length === 0 ? "הסוכן עוד לא מכיר אנשי קשר." : "לא נמצאו אנשי קשר."}</Empty>
      ) : (
        <ul className="space-y-2">
          {shown.map((c) => (
            <li key={c.id} className="flex items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white p-3">
              <div>
                {c.name ? (
                  <p className="font-medium">{c.name}</p>
                ) : (
                  <p className="font-medium text-amber-800">ממתין לשם</p>
                )}
                <bdi className="text-sm text-slate-700">{c.email}</bdi>
              </div>
              <PendingButton>{c.name ? "עריכה" : "תן שם"}</PendingButton>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
