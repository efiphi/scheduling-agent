import type { Account, Contact, DailySummary, HistoryEntry, ManagedUser, Settings } from "../domain/account";
import type { PendingAction } from "../domain/actions";
import type { QueueEvent } from "../domain/queue";

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
  /** Real-time queue changes (Server-Sent Events in Layer 1). Returns an unsubscribe function. */
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
  subscribeToQueue: () => () => {},
};
