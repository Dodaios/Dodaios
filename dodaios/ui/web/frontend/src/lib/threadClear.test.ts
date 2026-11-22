import { describe, expect, it } from "vitest";

import { isClearCommand } from "./threadClear";

describe("the thread's clear command", () => {
  it("is /clear and the names the CLI lists for it, with or without a name", () => {
    for (const text of ["/clear", "  /clear ", "/reset", "/new", "/clear login bug", "/clear two\nlines"]) {
      expect(isClearCommand(text), text).toBe(true);
    }
  });

  it("is no other word, and never part of a sentence or a path", () => {
    for (const text of ["clear", "/clearing", "/clear/all", "please /clear", "/context", "/usr/bin/clear", ""]) {
      expect(isClearCommand(text), text).toBe(false);
    }
  });
});
