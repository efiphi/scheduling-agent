import { redirect } from "react-router";

import type { components } from "../api/schema";
import type { Account } from "../domain/account";
import type { PendingAction } from "../domain/actions";
import type { AgentQuestion, DataSource, DecisionResult } from "./source";

// The real API (services/api), reached at /api through the Vite dev proxy or nginx, so the
// browser sees one origin: the session cookie is sent, and no CORS rules are needed.
// Types come from the API's OpenAPI schema (src/api/schema.ts, generated, never edited).
type ActionOut = components["schemas"]["ActionOut"];
type Me = components["schemas"]["Me"];
type QuestionOut = components["schemas"]["QuestionOut"];

const BASE = "/api";
const POLL_MS = 15_000;

/** Thrown by loaders when there is no session: the router sends the user to /login. */
function toLogin(): never {
  throw redirect("/login");
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { credentials: "same-origin" });
  if (response.status === 401) toLogin();
  if (!response.ok) throw new Error(`GET ${path} failed: ${response.status}`);
  return (await response.json()) as T;
}

export function toPendingAction(a: ActionOut): PendingAction {
  return {
    id: a.action_id,
    kind: a.kind as PendingAction["kind"],
    status: a.status === "executed" ? "approved" : (a.status as PendingAction["status"]),
    createdAt: a.created_at,
    expiresAt: a.expires_at,
    contentHash: a.content_hash,
    // Recipients always come from the thread (T5), so none is new.
    recipients: a.to.map((email) => ({ email, isNew: false })),
    slots: a.slots.map((s) => ({ start: s.start, end: s.end })),
    draft: a.body,
    flaggedSentences: [],
  };
}

export function createHttpSource(fetchCsrf: () => Promise<string> = defaultCsrf): DataSource {
  let csrf: string | undefined;

  async function post(path: string, body?: unknown): Promise<DecisionResult> {
    csrf ??= await fetchCsrf();
    const response = await fetch(`${BASE}${path}`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (response.ok) return { ok: true };
    const detail = await response.json().then((j: { detail?: unknown }) => j.detail, () => undefined);
    return { ok: false, reason: typeof detail === "string" ? detail : String(response.status) };
  }

  return {
    listPendingActions: async () => (await getJson<ActionOut[]>("/actions?status=pending")).map(toPendingAction),
    getAction: async (id) => {
      const response = await fetch(`${BASE}/actions/${encodeURIComponent(id)}`, { credentials: "same-origin" });
      if (response.status === 401) toLogin();
      if (response.status === 404) return null;
      return toPendingAction((await response.json()) as ActionOut);
    },
    getAccount: async (): Promise<Account> => {
      const me = await getJson<Me>("/me");
      csrf = me.csrf_token;
      return {
        agentStatus: me.status === "paused" ? "paused" : "active",
        google: "connected",
        backupNumbers: [],
        isAdmin: me.is_admin,
        spendCapReached: false,
      };
    },
    listQuestions: async (): Promise<AgentQuestion[]> =>
      (await getJson<QuestionOut[]>("/questions")).map((q) => ({
        id: q.question_id,
        question: q.question,
        createdAt: q.created_at,
      })),
    approve: (id, contentHash) => post(`/actions/${encodeURIComponent(id)}/approve`, { content_hash: contentHash }),
    reject: (id) => post(`/actions/${encodeURIComponent(id)}/reject`),
    dismissQuestion: (id) => post(`/questions/${encodeURIComponent(id)}/dismiss`),
    // Not in the API yet in the MVP: empty screens until their endpoints exist.
    listHistory: () => Promise.resolve([]),
    listContacts: () => Promise.resolve([]),
    getSettings: () => Promise.resolve(null),
    getSummary: () => Promise.resolve(null),
    listUsers: () => Promise.resolve([]),
    // MVP: poll for new actions instead of Server-Sent Events (docs/04-web-app.md, decision
    // recorded there). A card that appears is announced as "created".
    subscribeToQueue: (onEvent) => {
      const seen = new Set<string>();
      let first = true;
      const timer = setInterval(() => {
        void getJson<ActionOut[]>("/actions?status=pending").then(
          (actions) => {
            for (const a of actions) {
              if (!first && !seen.has(a.action_id)) onEvent({ type: "created", action: toPendingAction(a) });
              seen.add(a.action_id);
            }
            first = false;
          },
          () => undefined,
        );
      }, POLL_MS);
      return () => clearInterval(timer);
    },
  };
}

async function defaultCsrf(): Promise<string> {
  return (await getJson<Me>("/me")).csrf_token;
}
