import type { DataSource } from "../data/source";
import type { PendingAction } from "../domain/actions";

// Synthetic test data only: example.com addresses and made-up names, never real people.
export function makeAction(overrides: Partial<PendingAction> = {}): PendingAction {
  return {
    id: "act-1",
    kind: "reply_with_slots",
    status: "pending",
    createdAt: "2026-11-02T08:00:00+02:00",
    expiresAt: "2026-11-02T18:00:00+02:00",
    contentHash: "sha256:test",
    recipients: [{ email: "dani@acme.example.com", contactName: "דני — אקמה", isNew: false }],
    slots: [{ start: "2026-11-03T10:00:00+02:00", end: "2026-11-03T10:30:00+02:00" }],
    draft: "היי דני, אפשר באחד מהמועדים האלה.\n\nנשלח על ידי הסוכן של המשתמש.",
    flaggedSentences: [],
    ...overrides,
  };
}

export function sourceWith(actions: PendingAction[]): DataSource {
  return {
    listPendingActions: () => Promise.resolve(actions),
    getAction: (id) => Promise.resolve(actions.find((a) => a.id === id) ?? null),
  };
}
