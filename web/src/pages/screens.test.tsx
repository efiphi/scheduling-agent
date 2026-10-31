import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { notConnectedSource } from "../data/source";
import { sourceWith } from "../test/fixtures";
import { renderApp } from "../test/render";

const XSS = '<img src=x onerror="window.__pwned=true"><script>window.__pwned=true</script>';

describe("every screen in the map renders with no data", () => {
  it.each([
    ["/summary", "סיכום יומי"],
    ["/history", "היסטוריה"],
    ["/contacts", "אנשי קשר"],
    ["/settings", "הגדרות"],
    ["/settings/security", "אבטחה"],
    ["/admin/users", "ניהול משתמשים"],
    ["/login", "סוכן פגישות"],
    ["/invite/some-token", "הזמנה"],
    ["/onboarding", "הגדרה ראשונית"],
  ])("%s", async (path, heading) => {
    renderApp(path, notConnectedSource);
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
  });

  it("keeps the bottom nav off the screens before setup", async () => {
    renderApp("/login", notConnectedSource);
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("navigation", { name: "ניווט ראשי" })).not.toBeInTheDocument();
  });
});

describe("security screen", () => {
  it("test_t11_pause_button_pauses_the_agent", async () => {
    // ADR-014: pausing from any browser covers the case where no backup phone is at hand.
    const pauseAgent = vi.fn().mockResolvedValue({ ok: true });
    renderApp("/settings/security", { ...notConnectedSource, pauseAgent });
    await userEvent.click(await screen.findByRole("button", { name: "השהה סוכן" }));
    expect(pauseAgent).toHaveBeenCalledOnce();
    expect(await screen.findByRole("status")).toHaveTextContent("הסוכן הושהה");
  });

  it("asks for a fresh Google login before a sensitive change", async () => {
    const setStopCode = vi.fn().mockResolvedValue({ ok: false, reason: "login again" });
    renderApp("/settings/security", { ...notConnectedSource, setStopCode });
    await userEvent.type(await screen.findByLabelText("קוד עצירה חדש"), "purple elephant 42");
    const [saveStopCode] = screen.getAllByRole("button", { name: "שמור" });
    if (!saveStopCode) throw new Error("no save button");
    await userEvent.click(saveStopCode);
    expect(setStopCode).toHaveBeenCalledWith("purple elephant 42");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("להתחבר שוב");
    expect(alert.querySelector("a")?.getAttribute("href")).toBe("/api/auth/google/login");
  });

  it("shows the code to send for WhatsApp verification (ADR-017)", async () => {
    const startWhatsAppVerification = vi.fn().mockResolvedValue({ code: "K7P3Q9M2", agentNumber: "+1 555 0100", expiresInSeconds: 600 });
    renderApp("/settings/security", { ...notConnectedSource, startWhatsAppVerification });
    await userEvent.click(await screen.findByRole("button", { name: "קבל קוד אימות" }));
    expect(await screen.findByText("אימות K7P3Q9M2")).toBeInTheDocument();
    expect(screen.getByText("+1 555 0100")).toBeInTheDocument();
  });

  it("the stop code field never shows what is typed", async () => {
    renderApp("/settings/security", notConnectedSource);
    expect(await screen.findByLabelText("קוד עצירה חדש")).toHaveAttribute("type", "password");
  });
});

describe("onboarding wizard", () => {
  it("moves forward and back through the six steps", async () => {
    const user = userEvent.setup();
    renderApp("/onboarding", notConnectedSource);
    expect(await screen.findByText("שלב 1 מתוך 6")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "הקודם" })).toBeDisabled();

    for (let i = 0; i < 5; i++) await user.click(screen.getByRole("button", { name: "הבא" }));
    expect(screen.getByText("שלב 6 מתוך 6")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "סיום" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "הקודם" }));
    expect(screen.getByRole("heading", { level: 2, name: "אימות לבקשות חריגות" })).toBeInTheDocument();
  });
});

describe("contacts", () => {
  const source = sourceWith([], {
    listContacts: () =>
      Promise.resolve([
        { id: "1", name: "דני — אקמה", email: "dani@acme.example.com" },
        { id: "2", email: "new@other.example.com" },
      ]),
  });

  it("lists contacts waiting for a name first", async () => {
    renderApp("/contacts", source);
    const items = await screen.findAllByRole("listitem");
    expect(within(items[0] ?? document.body).getByText("ממתין לשם")).toBeInTheDocument();
  });

  it("filters by name or email", async () => {
    const user = userEvent.setup();
    renderApp("/contacts", source);
    await user.type(await screen.findByRole("searchbox", { name: "חיפוש אנשי קשר" }), "acme");
    expect(screen.getByText("dani@acme.example.com")).toBeInTheDocument();
    expect(screen.queryByText("new@other.example.com")).not.toBeInTheDocument();
  });
});

describe("history", () => {
  it("filters by channel", async () => {
    const user = userEvent.setup();
    renderApp(
      "/history",
      sourceWith([], {
        listHistory: () =>
          Promise.resolve([
            { id: "1", at: "2026-11-02T09:00:00+02:00", kind: "block_time", summary: "נחסמו שעתיים", channel: "whatsapp" },
            { id: "2", at: "2026-11-02T10:00:00+02:00", kind: "settings_change", summary: "שעות עבודה עודכנו", channel: "web" },
          ]),
      }),
    );
    await user.selectOptions(await screen.findByRole("combobox", { name: "ערוץ" }), "web");
    expect(screen.getByText("שעות עבודה עודכנו")).toBeInTheDocument();
    expect(screen.queryByText("נחסמו שעתיים")).not.toBeInTheDocument();
  });
});

describe("untrusted text on the new screens", () => {
  it("test_t19_skipped_email_sender_and_subject_stay_text", async () => {
    const { container } = renderApp(
      "/summary",
      sourceWith([], {
        getSummary: () =>
          Promise.resolve({
            meetingsThisWeek: 0,
            awaitingReply: 0,
            expiredYesterday: 0,
            skippedEmails: [{ id: "1", from: XSS, subject: XSS, receivedAt: "2026-11-02T07:00:00+02:00" }],
          }),
      }),
    );
    await screen.findByRole("heading", { name: "מיילים שהסוכן דילג עליהם" });
    expect(container.querySelector("img, script")).toBeNull();
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();
  });

  it("test_t19_contact_email_stays_text", async () => {
    const { container } = renderApp(
      "/contacts",
      sourceWith([], { listContacts: () => Promise.resolve([{ id: "1", email: XSS }]) }),
    );
    await screen.findByText("ממתין לשם");
    expect(container.querySelector("img, script")).toBeNull();
  });
});
