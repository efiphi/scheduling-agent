// Pending actions as the web app sees them (docs/04-web-app.md, "approval queue").
// In Layer 1 these types are replaced by ones generated from the API's OpenAPI schema.

export type ActionKind =
  | "reply_with_slots" // UC-M1: reply in the thread with 2–3 proposed slots
  | "create_event" // UC-M2 / UC-W1: create an event with a Meet link and invite
  | "reschedule_event" // UC-M4
  | "cancel_event" // UC-M5
  | "block_time"; // UC-C1 / UC-C2: calendar-only, no third party

export type ActionStatus = "pending" | "approved" | "rejected" | "expired" | "failed";

export type Channel = "email" | "whatsapp" | "web";

export interface Recipient {
  email: string;
  /** The unique name the user gave this contact (UC-M9), if known. */
  contactName?: string;
  /** Not in the thread before: must be highlighted and explicitly approved (T5, E2). */
  isNew: boolean;
}

export interface Slot {
  /** ISO 8601 with an explicit offset, e.g. 2026-11-03T10:00:00+02:00 (E3). */
  start: string;
  end: string;
  /** IANA zone of the other side when known and different from the user's (E3). */
  counterpartTimeZone?: string;
}

/** The message that triggered the action. Always untrusted, always shown as plain text (T19). */
export interface SourceMessage {
  channel: Channel;
  from: string;
  subject?: string;
  receivedAt: string;
  text: string;
}

export interface PendingAction {
  id: string;
  kind: ActionKind;
  status: ActionStatus;
  createdAt: string;
  /** End of the nearest workday that has not yet ended (E7). */
  expiresAt: string;
  /** Hash of the exact action content; an approval is bound to it (T3, T10). */
  contentHash: string;
  recipients: Recipient[];
  slots: Slot[];
  /** Full draft as it will be sent, including the disclosure line (invariant 10). */
  draft?: string;
  /** Sentences in the draft that go beyond scheduling (E5). */
  flaggedSentences: string[];
  /** Plain-language reason when the action is unusual and needs extra verification (T29). */
  anomalyReason?: string;
  /** Plain-language reason when execution failed (E13). */
  failureReason?: string;
  /** The agent's explanation of why it proposed this action. */
  explanation?: string;
  source?: SourceMessage;
}

export const actionKindLabel: Record<ActionKind, string> = {
  reply_with_slots: "תשובה עם מועדים",
  create_event: "קביעת פגישה",
  reschedule_event: "שינוי מועד",
  cancel_event: "ביטול פגישה",
  block_time: "חסימת זמן ביומן",
};

/** Queue order from docs/04-web-app.md: whatever expires first is on top. */
export function byExpiry(a: PendingAction, b: PendingAction): number {
  return Date.parse(a.expiresAt) - Date.parse(b.expiresAt);
}
