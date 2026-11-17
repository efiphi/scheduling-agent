import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { notConnectedSource } from "../data/source";
import { makeAction, sourceWith } from "../test/fixtures";
import { renderApp } from "../test/render";

describe("approval queue", () => {
  it("shows the empty state while nothing is connected", async () => {
    renderApp("/", notConnectedSource);
    expect(await screen.findByText("אין כרגע פעולות שמחכות לך.")).toBeInTheDocument();
  });

  it("puts the action that expires first on top", async () => {
    renderApp(
      "/",
      sourceWith([
        makeAction({ id: "late", kind: "cancel_event", expiresAt: "2026-11-04T18:00:00+02:00" }),
        makeAction({ id: "early", kind: "block_time", expiresAt: "2026-11-02T18:00:00+02:00" }),
      ]),
    );
    const cards = await screen.findAllByRole("article");
    const titles = cards.map((card) => within(card).getByRole("heading").textContent);
    expect(titles).toEqual(["חסימת זמן ביומן", "ביטול פגישה"]);
  });

  it("approves exactly what was shown: the card's content hash goes to the server", async () => {
    const approve = vi.fn().mockResolvedValue({ ok: true });
    renderApp("/", sourceWith([makeAction({ id: "a", contentHash: "sha256:shown" })], { approve }));
    await userEvent.click(await screen.findByRole("button", { name: "אשר" }));
    expect(approve).toHaveBeenCalledWith("a", "sha256:shown");
    expect(await screen.findByText("אין כרגע פעולות שמחכות לך.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("אושר באפליקציה");
  });

  it("keeps the card and explains when the content changed (T3)", async () => {
    const approve = vi.fn().mockResolvedValue({ ok: false, reason: "hash_mismatch" });
    renderApp("/", sourceWith([makeAction()], { approve }));
    await userEvent.click(await screen.findByRole("button", { name: "אשר" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("התוכן השתנה");
    expect(screen.getByRole("article")).toBeInTheDocument();
  });

  it("rejects, and edit is not available in the MVP", async () => {
    const reject = vi.fn().mockResolvedValue({ ok: true });
    renderApp("/", sourceWith([makeAction({ id: "r" })], { reject }));
    expect(await screen.findByRole("button", { name: "ערוך" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "דחה" }));
    expect(reject).toHaveBeenCalledWith("r");
  });

  it("shows the agent's questions as plain text (UC-M7, T19)", async () => {
    const listQuestions = () =>
      Promise.resolve([{ id: "q", question: "<img src=x onerror=alert(1)> מתי?", createdAt: "2026-11-02T08:00:00Z" }]);
    const { container } = renderApp("/", sourceWith([], { listQuestions }));
    expect(await screen.findByText("<img src=x onerror=alert(1)> מתי?")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});
