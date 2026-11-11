import { describe, expect, it } from "vitest";

import { shortModelLabel } from "./AgentComposer";

describe("shortModelLabel", () => {
  it("drops the family word the provider's mark already says", () => {
    expect(shortModelLabel("Claude Opus 5.5", "Claude Code")).toBe("Opus 5.5");
    expect(shortModelLabel("claude Sonnet 5.5", "Claude")).toBe("Sonnet 5.5");
  });

  it("keeps a name that does not start with that word, or would be left empty", () => {
    expect(shortModelLabel("GPT-5.5", "OpenAI")).toBe("GPT-5.5");
    expect(shortModelLabel("Claude", "Claude")).toBe("Claude");
    expect(shortModelLabel("Claudette 2", "Claude")).toBe("Claudette 2");
    expect(shortModelLabel("Opus 5.5", "")).toBe("Opus 5.5");
  });
});
