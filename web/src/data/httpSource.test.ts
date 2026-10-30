import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpSource } from "./httpSource";

const action = {
  action_id: "a1",
  kind: "reply_with_slots",
  status: "pending",
  to: ["dana@example.org"],
  subject: "Re: Call?",
  body: "Hi\n\n--\nsent by my assistant",
  slots: [{ start: "2026-11-03T08:00:00Z", end: "2026-11-03T08:30:00Z" }],
  content_hash: "sha256:abc",
  expires_at: "2026-11-03T16:00:00Z",
  created_at: "2026-11-02T08:00:00Z",
};

function respond(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

afterEach(() => vi.unstubAllGlobals());

describe("HTTP data source", () => {
  it("maps the API's actions to the queue's cards", async () => {
    vi.stubGlobal("fetch", vi.fn(() => respond(200, [action])));
    const cards = await createHttpSource().listPendingActions();
    const card = cards[0];
    if (!card) throw new Error("no card");
    expect(card).toMatchObject({ id: "a1", contentHash: "sha256:abc", draft: action.body });
    expect(card.recipients).toEqual([{ email: "dana@example.org", isNew: false }]);
  });

  it("sends the CSRF token and the hash with an approval (T10)", async () => {
    const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(() =>
      respond(200, { status: "approved" }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const result = await createHttpSource(() => Promise.resolve("csrf-1")).approve("a1", "sha256:abc");
    expect(result).toEqual({ ok: true });
    const call = fetchMock.mock.calls[0];
    if (!call) throw new Error("no call");
    const [url, init] = call;
    expect(url).toBe("/api/actions/a1/approve");
    expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe("csrf-1");
    expect(JSON.parse(String(init?.body))).toEqual({ content_hash: "sha256:abc" });
    expect(init?.credentials).toBe("same-origin");
  });

  it("returns the server's reason when an approval is refused", async () => {
    vi.stubGlobal("fetch", vi.fn(() => respond(409, { detail: "hash_mismatch" })));
    expect(await createHttpSource(() => Promise.resolve("t")).approve("a1", "x")).toEqual({ ok: false, reason: "hash_mismatch" });
  });

  it("sends the user to the login page without a session", async () => {
    vi.stubGlobal("fetch", vi.fn(() => respond(401, { detail: "login required" })));
    await expect(createHttpSource().listPendingActions()).rejects.toMatchObject({ status: 302 });
  });
});
