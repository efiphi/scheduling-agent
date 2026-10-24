// Types for the screens other than the approval queue (docs/04-web-app.md, "other screens").
// In Layer 1 these are replaced by types generated from the API's OpenAPI schema.

import type { ActionKind, Channel } from "./actions";

export interface HistoryEntry {
  id: string;
  at: string;
  /** An action the agent took, a settings change, or a security event on the user's own account. */
  kind: ActionKind | "settings_change" | "security_event";
  /** What happened, in plain language. */
  summary: string;
  /** Who decided: the user, or "agent" for calendar-only actions from a direct command. */
  decidedBy?: string;
  channel: Channel;
  contactName?: string;
}

export interface Contact {
  id: string;
  /** Unique name the user chose (UC-M9). Missing while the contact waits for a name. */
  name?: string;
  email: string;
}

/** A setting value plus when it last changed and from which channel (UC-A5). */
export interface Tracked<T> {
  value: T;
  changedAt?: string;
  changedVia?: Channel;
}

export interface Settings {
  workDays: Tracked<string>;
  workHours: Tracked<string>;
  endOfWorkday: Tracked<string>;
  bufferMinutes: Tracked<number>;
  maxMeetingsPerDay: Tracked<number>;
  defaultDurationMinutes: Tracked<number>;
  blockedTimes: Tracked<string[]>;
  meetingType: Tracked<string>;
  replyLanguage: Tracked<string>;
  timeZone: Tracked<string>;
}

export type ConnectionStatus = "connected" | "expired" | "disconnected";

export interface Account {
  agentStatus: "active" | "paused";
  google: ConnectionStatus;
  whatsappNumber?: string;
  /** Up to two pre-registered numbers the stop code is accepted from (ADR-014). */
  backupNumbers: string[];
  verificationMethod?: "pin" | "secret_question";
  isAdmin: boolean;
}

/** Only sender, subject and time are kept, for 7 days (UC-M8, E9). Untrusted text. */
export interface SkippedEmail {
  id: string;
  from: string;
  subject: string;
  receivedAt: string;
}

export interface DailySummary {
  meetingsThisWeek: number;
  awaitingReply: number;
  expiredYesterday: number;
  skippedEmails: SkippedEmail[];
}

export interface ManagedUser {
  email: string;
  status: "invited" | "active" | "removed";
}
