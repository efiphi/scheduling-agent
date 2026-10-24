import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";

import { routes } from "./routes";

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
}

describe("app shell", () => {
  it("opens on the approval queue", () => {
    renderAt("/");
    expect(screen.getByRole("heading", { name: "תור אישורים" })).toBeInTheDocument();
  });

  it("navigates between the four main screens from the bottom nav", async () => {
    const user = userEvent.setup();
    renderAt("/");
    const nav = screen.getByRole("navigation", { name: "ניווט ראשי" });

    for (const [link, heading] of [
      ["היסטוריה", "היסטוריה"],
      ["אנשי קשר", "אנשי קשר"],
      ["הגדרות", "הגדרות"],
      ["תור", "תור אישורים"],
    ] as const) {
      await user.click(within(nav).getByRole("link", { name: link }));
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
  });

  it("shows a not-found page for unknown paths", () => {
    renderAt("/no-such-page");
    expect(screen.getByRole("heading", { name: "הדף לא נמצא" })).toBeInTheDocument();
  });
});
