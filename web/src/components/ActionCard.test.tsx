import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";

import type { PendingAction } from "../domain/actions";
import { makeAction } from "../test/fixtures";
import { ActionCard } from "./ActionCard";

function renderCard(action: PendingAction) {
  const router = createMemoryRouter([{ path: "/", element: <ActionCard action={action} /> }]);
  return render(<RouterProvider router={router} />);
}

const incoming = {
  sender: "dana@example.org",
  subject: "שיחה על התקציב",
  summary: "השולח מבקש שיחה, ושואל גם על התקציב.",
  gmailUrl: "https://mail.google.com/mail/#all/t",
};

describe("action card", () => {
  it("shows who wrote, about what, and links to the original (ADR-019)", () => {
    renderCard(makeAction({ incoming }));
    expect(screen.getByText(incoming.sender)).toBeTruthy();
    expect(screen.getByText(incoming.summary)).toBeTruthy();
    expect(screen.getByRole("link", { name: "למייל המקורי" }).getAttribute("href")).toBe(incoming.gmailUrl);
  });

  it("test_t31_a_link_not_to_gmail_is_not_clickable", () => {
    renderCard(makeAction({ incoming: { ...incoming, gmailUrl: "https://evil.example.com/" } }));
    expect(screen.queryByRole("link", { name: "למייל המקורי" })).toBeNull();
  });

  it("says to read the original when there is no summary", () => {
    renderCard(makeAction({ incoming: { ...incoming, summary: undefined } }));
    expect(screen.getByText("אין תקציר למייל הזה. כדאי לקרוא אותו במקור.")).toBeTruthy();
  });

  it("test_t5_new_recipient_is_tagged", () => {
    renderCard(
      makeAction({
        recipients: [
          { email: "dani@acme.example.com", isNew: false },
          { email: "ceo@acme.example.com", isNew: true },
        ],
      }),
    );
    // Full address is always shown, and only the new recipient carries the tag (T5, E2).
    expect(screen.getByText("ceo@acme.example.com")).toBeInTheDocument();
    expect(screen.getAllByText("נמען חדש")).toHaveLength(1);
  });

  it("test_t29_anomaly_reason_shown_only_when_present", () => {
    const { unmount } = renderCard(makeAction());
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    unmount();

    renderCard(makeAction({ anomalyReason: "ביטול של יותר משתי פגישות" }));
    expect(screen.getByRole("note")).toHaveTextContent("ביטול של יותר משתי פגישות");
  });

  it("test_e3_shows_both_time_zones_when_counterpart_is_abroad", () => {
    renderCard(
      makeAction({
        slots: [
          {
            start: "2026-11-03T10:00:00+02:00",
            end: "2026-11-03T10:30:00+02:00",
            counterpartTimeZone: "America/New_York",
          },
        ],
      }),
    );
    expect(screen.getByText(/10:00–10:30 שעון ישראל/)).toBeInTheDocument();
    expect(screen.getByText("America/New_York")).toBeInTheDocument();
    // 10:00 in Israel is 03:00 in New York on that date.
    expect(screen.getByText(/03:00–03:30/)).toBeInTheDocument();
  });

  it("test_e5_flags_sentences_beyond_scheduling", () => {
    renderCard(makeAction({ flaggedSentences: ["אשלח לך הצעת מחיר עד מחר."] }));
    expect(screen.getByRole("region", { name: "משפטים שחורגים מתיאום" })).toHaveTextContent(
      "אשלח לך הצעת מחיר עד מחר.",
    );
  });
});
