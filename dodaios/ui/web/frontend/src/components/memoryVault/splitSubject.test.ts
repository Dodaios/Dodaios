import { describe, expect, it } from "vitest";
import { splitSubject } from "./MemoryBrowser";

describe("splitSubject", () => {
  it("splits what a memory is about from what it says", () => {
    expect(splitSubject("Lukas: born 1922 in San Francisco")).toEqual({
      subject: "Lukas",
      body: "Born 1922 in San Francisco",
    });
  });

  it("drops a trailing source note", () => {
    expect(splitSubject("The user's time zone is Europe/Berlin. Source: voice:user-direct 2026-10-02.").body).toBe(
      "The user's time zone is Europe/Berlin.",
    );
  });

  it("leaves a plain sentence whole", () => {
    expect(splitSubject("The user prefers replies in English.")).toEqual({
      subject: null,
      body: "The user prefers replies in English.",
    });
  });
});
