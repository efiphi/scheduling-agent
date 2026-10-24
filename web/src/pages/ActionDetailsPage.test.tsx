import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { makeAction, sourceWith } from "../test/fixtures";
import { renderApp } from "../test/render";

const XSS = '<img src=x onerror="window.__pwned=true"><script>window.__pwned=true</script>';

describe("action details", () => {
  it("test_t19_external_content_is_rendered_as_text", async () => {
    const action = makeAction({
      id: "xss",
      draft: `שלום ${XSS}`,
      flaggedSentences: [XSS],
      recipients: [{ email: `x@example.com${XSS}`, contactName: XSS, isNew: true }],
      source: {
        channel: "email",
        from: `${XSS} <attacker@example.com>`,
        subject: XSS,
        receivedAt: "2026-11-02T07:55:00+02:00",
        text: `Can we meet?\n${XSS}`,
      },
    });
    const { container } = renderApp("/actions/xss", sourceWith([action]));

    await screen.findByRole("heading", { name: "ההודעה המקורית" });
    // The payload is visible as literal text...
    expect(screen.getAllByText((t) => t.includes("<script>")).length).toBeGreaterThan(0);
    // ...and never becomes markup or runs.
    expect(container.querySelector("img, script")).toBeNull();
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();
  });

  it("shows the original message and the agent's explanation", async () => {
    renderApp(
      "/actions/act-1",
      sourceWith([
        makeAction({
          explanation: "המועדים פנויים בשעות העבודה שהגדרת.",
          source: {
            channel: "email",
            from: "dani@acme.example.com",
            subject: "שיחה השבוע?",
            receivedAt: "2026-11-02T07:55:00+02:00",
            text: "אפשר לקבוע שיחה השבוע?",
          },
        }),
      ]),
    );
    expect(await screen.findByText("אפשר לקבוע שיחה השבוע?")).toBeInTheDocument();
    expect(screen.getByText("המועדים פנויים בשעות העבודה שהגדרת.")).toBeInTheDocument();
  });

  it("shows not-found for an unknown action", async () => {
    renderApp("/actions/missing", sourceWith([]));
    expect(await screen.findByRole("heading", { name: "הפעולה לא נמצאה" })).toBeInTheDocument();
  });
});
