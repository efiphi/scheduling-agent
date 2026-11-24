import { redirect } from "react-router";

import type { components } from "../api/schema";
import type { Account, ConnectionStatus, Invite, ManagedUser } from "../domain/account";
import type { PendingAction } from "../domain/actions";
import type { AgentQuestion, DataSource, DecisionResult, InviteResult, SecurityStatus, WhatsAppVerification } from "./source";

// The real API (services/api), reached at /api through the Vite dev proxy or nginx, so the
// browser sees one origin: the session cookie is sent, and no CORS rules are needed.
// Types come from the API's OpenAPI schema (src/api/schema.ts, generated, never edited).
type ActionOut = components["schemas"]["ActionOut"];
type Me = components["schemas"]["Me"];
type QuestionOut = components["schemas"]["QuestionOut"];
type SecurityOut = components["schemas"]["SecurityOut"];
type VerificationOut = components["schemas"]["VerificationOut"];
type InviteOut = components["schemas"]["InviteOut"];
type InviteCreatedOut = components["schemas"]["InviteCreatedOut"];
type AdminUserOut = components["schemas"]["AdminUserOut"];
type InviteCheckOut = components["schemas"]["InviteCheckOut"];
type LoginUrlOut = components["schemas"]["LoginUrlOut"];

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

function connection(status: string): ConnectionStatus {
  if (status === "connected" || status === "expired") return status;
  return "disconnected"; // revoked, or never connected
}

/** A POST before login: no session, so no CSRF token. The invite token travels in the body (T22). */
async function postPublic<T>(path: string, body: unknown): Promise<T | null> {
  const response = await fetch(`${BASE}${path}`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return response.ok ? ((await response.json()) as T) : null;
}

export function toPendingAction(a: ActionOut): PendingAction {
  return {
    id: a.action_id,
    kind: a.kind as PendingAction["kind"],
    status: a.status === "executed" ? "approved" : (a.status as PendingAction["status"]),
    createdAt: a.created_at,
    expiresAt: a.expires_at,
    contentHash: a.content_hash,
    incoming: a.incoming
      ? {
          sender: a.incoming.sender,
          subject: a.incoming.subject,
          summary: a.incoming.summary ?? undefined,
        }
      : undefined,
    // Recipients always come from the thread (T5), so none is new.
    recipients: a.to.map((email) => ({ email, isNew: false })),
    slots: a.slots.map((s) => ({ start: s.start, end: s.end })),
    draft: a.body,
    flaggedSentences: [],
  };
}

export function createHttpSource(fetchCsrf: () => Promise<string> = defaultCsrf): DataSource {
  let csrf: string | undefined;

  async function send(method: string, path: string, body?: unknown): Promise<Response> {
    csrf ??= await fetchCsrf();
    return fetch(`${BASE}${path}`, {
      method,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  }

  async function result(response: Response): Promise<DecisionResult> {
    if (response.ok) return { ok: true };
    const detail = await response.json().then((j: { detail?: unknown }) => j.detail, () => undefined);
    return { ok: false, reason: typeof detail === "string" ? detail : String(response.status) };
  }

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
        google: connection(me.google_status),
        whatsappVerified: me.whatsapp_verified,
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
    getSecurity: async (): Promise<SecurityStatus> => {
      const s = await getJson<SecurityOut>("/security");
      return {
        agentStatus: s.agent_status === "paused" ? "paused" : "active",
        whatsappVerified: s.whatsapp_verified,
        stopCodeSet: s.stop_code_set,
        backupNumbers: s.backup_numbers,
      };
    },
    pauseAgent: () => post("/security/pause"),
    resumeAgent: () => post("/security/resume"),
    setStopCode: async (code) => result(await send("PUT", "/security/stop-code", { code })),
    setBackupNumbers: async (numbers) => result(await send("PUT", "/security/backup-numbers", { numbers })),
    startWhatsAppVerification: async (): Promise<WhatsAppVerification | null> => {
      const response = await send("POST", "/whatsapp/verify");
      if (!response.ok) return null;
      const v = (await response.json()) as VerificationOut;
      return { code: v.code, agentNumber: v.agent_number, expiresInSeconds: v.expires_in_seconds };
    },
    logOutEverywhere: async () => result(await send("DELETE", "/sessions")),
    checkInvite: async (token) => {
      const found = await postPublic<InviteCheckOut>("/invites/check", { token });
      return found && { emailHint: found.email_hint };
    },
    startInviteLogin: async (token) => (await postPublic<LoginUrlOut>("/auth/google/invite", { token }))?.url ?? null,
    connectGoogle: async (returnTo) => {
      const response = await send("POST", "/integrations/google/connect", { return_to: returnTo });
      return response.ok ? ((await response.json()) as LoginUrlOut).url : null;
    },
    listInvites: async (): Promise<Invite[]> =>
      (await getJson<InviteOut[]>("/admin/invites")).map((i) => ({
        id: i.invite_id,
        email: i.email,
        status: i.status as Invite["status"],
        expiresAt: i.expires_at,
      })),
    createInvite: async (email): Promise<InviteResult> => {
      const response = await send("POST", "/admin/invites", { email });
      if (response.ok) return { ok: true, link: ((await response.json()) as InviteCreatedOut).link };
      const failed = await result(response);
      return { ok: false, reason: failed.ok ? "" : failed.reason };
    },
    revokeInvite: async (id) => result(await send("DELETE", `/admin/invites/${encodeURIComponent(id)}`)),
    listUsers: async (): Promise<ManagedUser[]> =>
      (await getJson<AdminUserOut[]>("/admin/users")).map((u) => ({
        email: u.email,
        status: u.status === "paused" ? "paused" : "active",
        isAdmin: u.is_admin,
        whatsappVerified: u.whatsapp_verified,
        google: connection(u.google_status),
      })),
    // Not in the API yet in the MVP: empty screens until their endpoints exist.
    listHistory: () => Promise.resolve([]),
    listContacts: () => Promise.resolve([]),
    getSettings: () => Promise.resolve(null),
    getSummary: () => Promise.resolve(null),
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
