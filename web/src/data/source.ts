import type { PendingAction } from "../domain/actions";

/**
 * Everything the UI reads goes through this interface. Screens never fetch directly,
 * so connecting the real API in Layer 1 means replacing one implementation.
 */
export interface DataSource {
  listPendingActions(): Promise<PendingAction[]>;
  getAction(id: string): Promise<PendingAction | null>;
}

/** Until the API exists, the app has no data: every screen shows its empty state. */
export const notConnectedSource: DataSource = {
  listPendingActions: () => Promise.resolve([]),
  getAction: () => Promise.resolve(null),
};
