import { describe, expect, it } from "vitest";
import { MAX_ACCOUNTS, suggestedAccounts } from "./accounts";
import { cleanName } from "./firstConversationApi";

const CATALOG = ["gmail", "google_calendar", "outlook", "github", "notion", "spotify", "todoist", "home_assistant"].map(
  (id) => ({ id, display_name: id }),
);

describe("suggestedAccounts", () => {
  it("puts the accounts the chosen topics need first", () => {
    const ids = suggestedAccounts(["music", "home"], CATALOG).map((a) => a.id);
    expect(ids.slice(0, 2)).toEqual(["spotify", "home_assistant"]);
    expect(ids).toHaveLength(MAX_ACCOUNTS);
  });

  it("offers only what the catalog lists", () => {
    const ids = suggestedAccounts(["tasks"], [{ id: "todoist" }, { id: "gmail" }]).map((a) => a.id);
    expect(ids).toEqual(["todoist", "gmail"]);
  });

  it("falls back to the common accounts without topics", () => {
    expect(suggestedAccounts([], CATALOG).map((a) => a.id)).toEqual([
      "gmail",
      "google_calendar",
      "outlook",
      "github",
      "notion",
      "spotify",
    ]);
  });
});

describe("cleanName", () => {
  it("keeps one tidy line", () => {
    expect(cleanName('  "Ana  Maria". \n')).toBe("Ana Maria");
    expect(cleanName("x".repeat(80))).toHaveLength(60);
    expect(cleanName("   ")).toBe("");
  });
});
