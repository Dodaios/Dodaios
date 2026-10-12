import { describe, expect, it } from "vitest";

import {
  OFFICIAL_REPO_LABEL,
  OFFICIAL_REPO_SLUG,
  OFFICIAL_REPO_URL,
  PRODUCT_NAME,
} from "@/lib/branding";

describe("branding", () => {
  it("shows the product display name", () => {
    expect(PRODUCT_NAME).toBe("Dodaios");
  });

  it("keeps the repository link values", () => {
    expect(OFFICIAL_REPO_SLUG).toBe("PersonalJarvis/PersonalJarvis");
    expect(OFFICIAL_REPO_URL).toBe(
      "https://github.com/PersonalJarvis/PersonalJarvis",
    );
    expect(OFFICIAL_REPO_LABEL).toBe(
      "github.com/PersonalJarvis/PersonalJarvis",
    );
  });
});
