import { describe, expect, it } from "vitest";

import {
  MCP_TOOLS_SERVER_NAMES,
  OFFICIAL_REPO_LABEL,
  OFFICIAL_REPO_SLUG,
  OFFICIAL_REPO_URL,
  PRODUCT_NAME,
} from "@/lib/branding";

describe("branding", () => {
  it("shows the product display name", () => {
    expect(PRODUCT_NAME).toBe("Dodaios");
  });

  it("links to the official repository", () => {
    expect(OFFICIAL_REPO_SLUG).toBe("Dodaios/Dodaios");
    expect(OFFICIAL_REPO_URL).toBe("https://github.com/Dodaios/Dodaios");
    expect(OFFICIAL_REPO_LABEL).toBe("github.com/Dodaios/Dodaios");
  });

  it("names the MCP tools server, the current name first and the earlier one kept", () => {
    expect(MCP_TOOLS_SERVER_NAMES).toEqual(["dodaios", "jarvis"]);
  });
});
