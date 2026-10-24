import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

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

  it("does not wire approve/edit/reject before the API exists", async () => {
    renderApp("/", sourceWith([makeAction()]));
    for (const name of ["אשר", "ערוך", "דחה"]) {
      expect(await screen.findByRole("button", { name })).toBeDisabled();
    }
  });
});
