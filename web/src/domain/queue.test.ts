import { describe, expect, it } from "vitest";

import { makeAction } from "../test/fixtures";
import { applyQueueEvent, type QueueState } from "./queue";

const start: QueueState = { actions: [makeAction({ id: "a" }), makeAction({ id: "b" })] };

describe("applyQueueEvent", () => {
  it("removes an action approved on another channel and says where", () => {
    const next = applyQueueEvent(start, { type: "decided", id: "a", decision: "approved", channel: "whatsapp" });
    expect(next.actions.map((a) => a.id)).toEqual(["b"]);
    expect(next.notice).toBe("אושר בווטסאפ");
  });

  it("ignores a decision about an action that is not in the queue", () => {
    const next = applyQueueEvent(start, { type: "decided", id: "zzz", decision: "rejected", channel: "web" });
    expect(next).toBe(start);
  });

  it("test_e7_expired_action_stays_visible_and_marked", () => {
    const next = applyQueueEvent(start, { type: "expired", id: "b" });
    expect(next.actions.find((a) => a.id === "b")?.status).toBe("expired");
    expect(next.actions).toHaveLength(2);
  });

  it("test_e13_failed_action_keeps_a_reason", () => {
    const next = applyQueueEvent(start, { type: "failed", id: "a", reason: "החיבור ל-Google פג" });
    expect(next.actions.find((a) => a.id === "a")).toMatchObject({ status: "failed", failureReason: "החיבור ל-Google פג" });
  });

  it("adds a new action without duplicating an existing id", () => {
    const next = applyQueueEvent(start, { type: "created", action: makeAction({ id: "a", kind: "cancel_event" }) });
    expect(next.actions.map((a) => a.id).sort()).toEqual(["a", "b"]);
    expect(next.actions.find((a) => a.id === "a")?.kind).toBe("cancel_event");
  });

  it("does not change the state it was given", () => {
    const before = JSON.stringify(start);
    applyQueueEvent(start, { type: "expired", id: "a" });
    expect(JSON.stringify(start)).toBe(before);
  });
});
