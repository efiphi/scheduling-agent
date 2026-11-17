import { describe, expect, it } from "vitest";

import html from "../../index.html?raw";

// The whole UI is Hebrew-first: direction is set once on <html>, not per component.
describe("index.html", () => {
  it("is right-to-left Hebrew", () => {
    expect(html).toMatch(/<html lang="he" dir="rtl">/);
  });
});
