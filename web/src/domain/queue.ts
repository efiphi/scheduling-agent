import type { Channel, PendingAction } from "./actions";

// Real-time changes to the approval queue (docs/04-web-app.md, "special states").
// In Layer 1 these arrive from the API over Server-Sent Events; WhatsApp and the
// web app stay in sync because both apply the same events.
export type QueueEvent =
  | { type: "created"; action: PendingAction }
  | { type: "decided"; id: string; decision: "approved" | "rejected"; channel: Channel }
  | { type: "expired"; id: string }
  | { type: "failed"; id: string; reason: string };

export interface QueueState {
  actions: PendingAction[];
  /** Short message for the user about a change they did not make here, e.g. "approved on WhatsApp". */
  notice?: string;
}

const decidedVia: Record<Channel, string> = {
  whatsapp: "בווטסאפ",
  web: "באפליקציה",
  email: "במייל",
};

/** Pure: same state and event always give the same result, so it is easy to test. */
export function applyQueueEvent(state: QueueState, event: QueueEvent): QueueState {
  switch (event.type) {
    case "created":
      return { actions: [...state.actions.filter((a) => a.id !== event.action.id), event.action] };

    case "decided": {
      if (!state.actions.some((a) => a.id === event.id)) return state;
      const verb = event.decision === "approved" ? "אושר" : "נדחה";
      return {
        actions: state.actions.filter((a) => a.id !== event.id),
        notice: `${verb} ${decidedVia[event.channel]}`,
      };
    }

    case "expired":
      // E7: the card stays, locked, so the user can see what expired and requeue it.
      return { ...state, actions: state.actions.map((a) => (a.id === event.id ? { ...a, status: "expired" } : a)) };

    case "failed":
      // E13: a failure never disappears silently; the card comes back with a plain reason.
      return {
        ...state,
        actions: state.actions.map((a) =>
          a.id === event.id ? { ...a, status: "failed", failureReason: event.reason } : a,
        ),
      };
  }
}
