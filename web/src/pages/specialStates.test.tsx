import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Account } from "../domain/account";
import type { QueueEvent } from "../domain/queue";
import { makeAction, sourceWith } from "../test/fixtures";
import { renderApp } from "../test/render";

const healthy: Account = {
  agentStatus: "active",
  google: "connected",
  backupNumbers: [],
  isAdmin: false,
  spendCapReached: false,
};

function withAccount(overrides: Partial<Account>) {
  return sourceWith([], { getAccount: () => Promise.resolve({ ...healthy, ...overrides }) });
}

describe("status banners", () => {
  it("shows nothing when everything is fine", async () => {
    renderApp("/", withAccount({}));
    await screen.findByRole("heading", { name: "תור אישורים" });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("test_t11_paused_banner_on_every_screen", async () => {
    for (const path of ["/", "/settings", "/contacts"]) {
      const { unmount } = renderApp(path, withAccount({ agentStatus: "paused" }));
      expect(await screen.findByRole("alert", { name: "הסוכן מושהה" })).toBeInTheDocument();
      unmount();
    }
  });

  it("test_e13_google_expired_banner_offers_reconnect", async () => {
    renderApp("/", withAccount({ google: "expired" }));
    const banner = await screen.findByRole("alert", { name: "החיבור ל-Google" });
    expect(banner).toHaveTextContent("החיבור ל-Google פג.");
    expect(screen.getByRole("button", { name: "חיבור מחדש" })).toBeInTheDocument();
  });

  it("test_t24_spend_cap_banner", async () => {
    renderApp("/", withAccount({ spendCapReached: true }));
    expect(await screen.findByRole("alert", { name: "תקרת הוצאה" })).toHaveTextContent(
      "הסוכן עצר לעיבוד מיילים חדשים עד מחר.",
    );
  });

  it("shows an offline banner when the network drops", async () => {
    renderApp("/", withAccount({}));
    await screen.findByRole("heading", { name: "תור אישורים" });
    const original = Object.getOwnPropertyDescriptor(Navigator.prototype, "onLine");
    Object.defineProperty(navigator, "onLine", { configurable: true, get: () => false });
    try {
      act(() => {
        window.dispatchEvent(new Event("offline"));
      });
      expect(screen.getByRole("alert", { name: "אין חיבור לרשת" })).toBeInTheDocument();
    } finally {
      delete (navigator as { onLine?: boolean }).onLine;
      if (original) Object.defineProperty(Navigator.prototype, "onLine", original);
    }
  });
});

describe("action card states", () => {
  it("test_e7_expired_action_is_locked_with_requeue", async () => {
    renderApp("/", sourceWith([makeAction({ status: "expired" })]));
    expect(await screen.findByText("הפעולה פגה. אפשר להחזיר אותה לתור.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "אשר" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "החזר לתור" })).toBeInTheDocument();
  });

  it("test_e13_failed_action_shows_reason", async () => {
    renderApp("/", sourceWith([makeAction({ status: "failed", failureReason: "המועד כבר לא פנוי" })]));
    expect(await screen.findByRole("alert")).toHaveTextContent("נכשל: המועד כבר לא פנוי");
  });
});

describe("real-time queue", () => {
  it("removes a card approved on WhatsApp and says so", async () => {
    let push: ((e: QueueEvent) => void) | undefined;
    const source = sourceWith([makeAction({ id: "a" }), makeAction({ id: "b", kind: "block_time" })], {
      subscribeToQueue: (onEvent) => {
        push = onEvent;
        return () => {};
      },
    });
    renderApp("/", source);
    expect(await screen.findAllByRole("article")).toHaveLength(2);
    await waitFor(() => expect(push).toBeDefined());

    act(() => push?.({ type: "decided", id: "a", decision: "approved", channel: "whatsapp" }));

    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(screen.getByRole("status")).toHaveTextContent("אושר בווטסאפ");
  });

  it("locks a card that expires while it is open", async () => {
    let push: ((e: QueueEvent) => void) | undefined;
    const source = sourceWith([makeAction({ id: "a" })], {
      subscribeToQueue: (onEvent) => {
        push = onEvent;
        return () => {};
      },
    });
    renderApp("/", source);
    await screen.findByRole("button", { name: "אשר" });
    // The page subscribes in an effect, which can run after the button is on screen. On a
    // slow machine (CI) an event sent before that would be lost, so wait for it.
    await waitFor(() => expect(push).toBeDefined());

    act(() => push?.({ type: "expired", id: "a" }));

    expect(screen.getByText("הפעולה פגה. אפשר להחזיר אותה לתור.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "אשר" })).not.toBeInTheDocument();
  });
});
