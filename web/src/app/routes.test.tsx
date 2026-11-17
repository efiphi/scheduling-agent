import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { notConnectedSource } from "../data/source";
import { renderApp } from "../test/render";

describe("app shell", () => {
  it("opens on the approval queue", async () => {
    renderApp("/", notConnectedSource);
    expect(await screen.findByRole("heading", { name: "תור אישורים" })).toBeInTheDocument();
  });

  it("navigates between the four main screens from the bottom nav", async () => {
    const user = userEvent.setup();
    renderApp("/", notConnectedSource);
    const nav = await screen.findByRole("navigation", { name: "ניווט ראשי" });

    for (const [link, heading] of [
      ["היסטוריה", "היסטוריה"],
      ["אנשי קשר", "אנשי קשר"],
      ["הגדרות", "הגדרות"],
      ["תור", "תור אישורים"],
    ] as const) {
      await user.click(within(nav).getByRole("link", { name: link }));
      expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
    }
  });

  it("shows a not-found page for unknown paths", async () => {
    renderApp("/no-such-page", notConnectedSource);
    expect(await screen.findByRole("heading", { name: "הדף לא נמצא" })).toBeInTheDocument();
  });
});
