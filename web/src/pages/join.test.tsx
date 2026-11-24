import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { notConnectedSource, type DataSource } from "../data/source";
import type { Account } from "../domain/account";
import { leaveApp } from "../lib/google";
import { renderApp } from "../test/render";

// Joining by invite and connecting Google (UC-A1, UC-A6). Synthetic addresses only.

const newUser: Account = {
  agentStatus: "active",
  google: "disconnected",
  whatsappVerified: false,
  backupNumbers: [],
  isAdmin: false,
  spendCapReached: false,
};

function source(overrides: Partial<DataSource>): DataSource {
  return { ...notConnectedSource, getAccount: () => Promise.resolve(newUser), ...overrides };
}

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("invite link", () => {
  it("test_t22_reads_the_token_from_the_fragment_and_removes_it", async () => {
    window.history.replaceState(null, "", "/invite#tok-123456789012345678901234567890");
    const checkInvite = vi.fn().mockResolvedValue({ emailHint: "n***@example.com" });
    const startInviteLogin = vi.fn().mockResolvedValue("https://accounts.example/auth?state=s");
    const go = vi.spyOn(leaveApp, "to").mockImplementation(() => undefined);
    renderApp("/invite", source({ checkInvite, startInviteLogin }));

    expect(await screen.findByText("n***@example.com")).toBeInTheDocument();
    expect(checkInvite).toHaveBeenCalledWith("tok-123456789012345678901234567890");
    expect(window.location.hash).toBe(""); // gone from the address bar and the history

    await userEvent.click(screen.getByRole("button", { name: "התחברות עם Google" }));
    expect(startInviteLogin).toHaveBeenCalledWith("tok-123456789012345678901234567890");
    expect(go).toHaveBeenCalledWith("https://accounts.example/auth?state=s");
  });

  it("test_t14_a_dead_invite_says_so_without_detail", async () => {
    window.history.replaceState(null, "", "/invite#tok-unknown-000000000000000000000000");
    renderApp("/invite", source({ checkInvite: vi.fn().mockResolvedValue(null) }));
    expect(await screen.findByText("ההזמנה לא נמצאה, פגה או כבר נוצלה.")).toBeInTheDocument();
  });
});

describe("login refusals", () => {
  it("explains a refused account", async () => {
    renderApp("/login?error=not_invited", notConnectedSource);
    expect(await screen.findByText(/החשבון הזה לא מוזמן למערכת/)).toBeInTheDocument();
  });

  it("test_t19_shows_nothing_for_an_unknown_error_code", async () => {
    renderApp("/login?error=%3Cscript%3Ealert(1)%3C/script%3E", notConnectedSource);
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("alert(1)");
  });
});

describe("onboarding", () => {
  it("test_t16_connecting_google_goes_to_the_gateway_with_a_ticket", async () => {
    const connectGoogle = vi.fn().mockResolvedValue("https://agent.example/oauth/google/start?ticket=t");
    const go = vi.spyOn(leaveApp, "to").mockImplementation(() => undefined);
    renderApp("/onboarding", source({ connectGoogle }));
    await userEvent.click(await screen.findByRole("button", { name: "חיבור ל-Google" }));
    expect(connectGoogle).toHaveBeenCalledWith("onboarding");
    expect(go).toHaveBeenCalledWith("https://agent.example/oauth/google/start?ticket=t");
  });

  it("shows the gateway's outcome after returning", async () => {
    renderApp("/onboarding?google=wrong_account", source({}));
    expect(await screen.findByText(/זה לא החשבון שאיתו נכנסת/)).toBeInTheDocument();
  });

  it("walks to the WhatsApp step and shows the code to send", async () => {
    const startWhatsAppVerification = vi.fn().mockResolvedValue({ code: "K7P3Q9M2", agentNumber: "+1 555 0100", expiresInSeconds: 600 });
    renderApp("/onboarding", source({ startWhatsAppVerification }));
    await userEvent.click(await screen.findByRole("button", { name: "דלג בינתיים" }));
    await userEvent.click(screen.getByRole("button", { name: "קבל קוד אימות" }));
    expect(await screen.findByText("אימות K7P3Q9M2")).toBeInTheDocument();
  });
});

describe("admin: inviting", () => {
  const admin: Account = { ...newUser, google: "connected", whatsappVerified: true, isAdmin: true };

  it("shows the link once, with the manual steps", async () => {
    const createInvite = vi.fn().mockResolvedValue({ ok: true, link: "https://agent.example/invite#abc" });
    renderApp("/admin/users", source({ getAccount: () => Promise.resolve(admin), createInvite }));
    await userEvent.type(await screen.findByLabelText("כתובת המייל של המוזמן"), "new-member@example.com");
    await userEvent.click(screen.getByRole("button", { name: "הזמן" }));
    expect(createInvite).toHaveBeenCalledWith("new-member@example.com");
    expect(await screen.findByText("https://agent.example/invite#abc")).toBeInTheDocument();
    expect(screen.getByText(/משתמש בדיקה ב-Google Cloud/)).toBeInTheDocument();
  });

  it("explains why an invite was refused", async () => {
    const createInvite = vi.fn().mockResolvedValue({ ok: false, reason: "already a user" });
    renderApp("/admin/users", source({ getAccount: () => Promise.resolve(admin), createInvite }));
    await userEvent.type(await screen.findByLabelText("כתובת המייל של המוזמן"), "member@example.com");
    await userEvent.click(screen.getByRole("button", { name: "הזמן" }));
    expect(await screen.findByText("לכתובת הזאת כבר יש משתמש.")).toBeInTheDocument();
  });

  it("lists invites and revokes a pending one", async () => {
    const revokeInvite = vi.fn().mockResolvedValue({ ok: true });
    const listInvites = vi.fn().mockResolvedValue([
      { id: "i1", email: "new-member@example.com", status: "pending", expiresAt: "2026-11-27T18:00:00+02:00" },
      { id: "i2", email: "old@example.com", status: "used", expiresAt: "2026-11-20T18:00:00+02:00" },
    ]);
    renderApp("/admin/users", source({ getAccount: () => Promise.resolve(admin), listInvites, revokeInvite }));
    expect(await screen.findByText("old@example.com")).toBeInTheDocument();
    const [revoke, ...others] = screen.getAllByRole("button", { name: "ביטול" });
    expect(others).toHaveLength(0); // only the pending one can be revoked
    if (!revoke) throw new Error("no revoke button");
    await userEvent.click(revoke);
    expect(revokeInvite).toHaveBeenCalledWith("i1");
  });

  it("links to user management from settings for an admin only", async () => {
    renderApp("/settings", source({ getAccount: () => Promise.resolve(admin) }));
    expect(await screen.findByRole("link", { name: /ניהול משתמשים/ })).toBeInTheDocument();
  });
});
