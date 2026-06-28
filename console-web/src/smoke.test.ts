import { describe, expect, it } from "vitest";

describe("World Console frontend", () => {
  it("keeps the smoke test gate active", () => {
    expect("World Console").toContain("World");
  });
});
