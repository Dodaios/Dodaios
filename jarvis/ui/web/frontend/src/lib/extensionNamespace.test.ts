import { describe, expect, it } from "vitest";
import {
  EXTENSION_NAMESPACE,
  EXTENSION_NAMESPACES,
  extensionOf,
  LEGACY_EXTENSION_NAMESPACES,
  usageCardPaths,
} from "./extensionNamespace";

describe("the plugin manifest namespace", () => {
  it("writes the new namespace and keeps reading the earlier one", () => {
    expect(EXTENSION_NAMESPACE).toBe("io.github.dodaios");
    expect(LEGACY_EXTENSION_NAMESPACES).toEqual(["io.github.personaljarvis"]);
    expect(EXTENSION_NAMESPACES).toEqual(["io.github.dodaios", "io.github.personaljarvis"]);
  });

  it("finds a manifest's block under either namespace", () => {
    const block = { display_name: "TodoFox" };
    for (const namespace of EXTENSION_NAMESPACES) {
      expect(extensionOf({ extensions: { [namespace]: block } })).toBe(block);
    }
  });

  it("prefers the current namespace when a manifest carries both", () => {
    const current = { display_name: "Current" };
    const manifest = { extensions: { "io.github.personaljarvis": { display_name: "Earlier" }, "io.github.dodaios": current } };
    expect(extensionOf(manifest)).toBe(current);
  });

  it("answers nothing for a manifest without a block of ours", () => {
    expect(extensionOf({})).toBeUndefined();
    expect(extensionOf(null)).toBeUndefined();
    expect(extensionOf({ extensions: null })).toBeUndefined();
    expect(extensionOf({ extensions: { "com.example.other": { display_name: "x" } } })).toBeUndefined();
  });

  it("looks for the usage card in the current directory first, then the earlier one", () => {
    expect(usageCardPaths()).toEqual(["io.github.dodaios/usage-card.md", "io.github.personaljarvis/usage-card.md"]);
    expect(usageCardPaths("pkg/")).toEqual(["pkg/io.github.dodaios/usage-card.md", "pkg/io.github.personaljarvis/usage-card.md"]);
  });
});
