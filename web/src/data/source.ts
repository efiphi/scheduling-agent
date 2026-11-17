import type { Account, Contact, DailySummary, HistoryEntry, ManagedUser, Settings } from "../domain/account";
import type { PendingAction } from "../domain/actions";
import type { QueueEvent } from "../domain/queue";

/** A question from the agent when it could not decide (UC-M7). Untrusted text: plain only. */
export interface AgentQuestion {
  id: string;
  question: string;
  createdAt: string;
}

export type DecisionResult = { ok: true } | { ok: false; reason: string };

/** What the security screen shows. Backup numbers arrive masked to their last four digits. */
export interface SecurityStatus {
  agentStatus: "active" | "paused";
  whatsappVerified: boolean;
  stopCodeSet: boolean;
  backupNumbers: string[];
}

export interface WhatsAppVerification {
  code: string;
  agentNumber: string;
  expiresInSeconds: number;
}

/**
 * Everything the UI reads goes through this interface. Screens never fetch directly,
 * so connecting the real API in Layer 1 means replacing one implementation.
 */
export interface DataSource {
  listPendingActions(): Promise<PendingAction[]>;
  getAction(id: string): Promise<PendingAction | null>;
  listHistory(): Promise<HistoryEntry[]>;
  listContacts(): Promise<Contact[]>;
  getSettings(): Promise<Settings | null>;
  getAccount(): Promise<Account | null>;
  getSummary(): Promise<DailySummary | null>;
  listUsers(): Promise<ManagedUser[]>;
  listQuestions(): Promise<AgentQuestion[]>;
  /** Approve exactly what was shown: the hash binds the approval to that content (T3, T10). */
  approve(id: string, contentHash: string): Promise<DecisionResult>;
  reject(id: string): Promise<DecisionResult>;
  dismissQuestion(id: string): Promise<DecisionResult>;
  getSecurity(): Promise<SecurityStatus | null>;
  pauseAgent(): Promise<DecisionResult>;
  resumeAgent(): Promise<DecisionResult>;
  setStopCode(code: string): Promise<DecisionResult>;
  setBackupNumbers(numbers: string[]): Promise<DecisionResult>;
  startWhatsAppVerification(): Promise<WhatsAppVerification | null>;
  logOutEverywhere(): Promise<DecisionResult>;
  /** Queue changes made elsewhere (WhatsApp, expiry). Returns an unsubscribe function. */
  subscribeToQueue(onEvent: (event: QueueEvent) => void): () => void;
}

/** Until the API exists, the app has no data: every screen shows its empty state. */
export const notConnectedSource: DataSource = {
  listPendingActions: () => Promise.resolve([]),
  getAction: () => Promise.resolve(null),
  listHistory: () => Promise.resolve([]),
  listContacts: () => Promise.resolve([]),
  getSettings: () => Promise.resolve(null),
  getAccount: () => Promise.resolve(null),
  getSummary: () => Promise.resolve(null),
  listUsers: () => Promise.resolve([]),
  listQuestions: () => Promise.resolve([]),
  approve: () => Promise.resolve({ ok: false, reason: "not_connected" }),
  reject: () => Promise.resolve({ ok: false, reason: "not_connected" }),
  dismissQuestion: () => Promise.resolve({ ok: false, reason: "not_connected" }),
  getSecurity: () => Promise.resolve(null),
  pauseAgent: () => Promise.resolve({ ok: false, reason: "not_connected" }),
  resumeAgent: () => Promise.resolve({ ok: false, reason: "not_connected" }),
  setStopCode: () => Promise.resolve({ ok: false, reason: "not_connected" }),
  setBackupNumbers: () => Promise.resolve({ ok: false, reason: "not_connected" }),
  startWhatsAppVerification: () => Promise.resolve(null),
  logOutEverywhere: () => Promise.resolve({ ok: false, reason: "not_connected" }),
  subscribeToQueue: () => () => {},
};
