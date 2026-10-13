import { describe, expect, it } from "vitest";

import type { Plugin } from "@/views/PluginsView";
import {
  catalogSections,
  categorySectionId,
  COMMUNITY_SECTION,
  homeSectionId,
  isInstalled,
  ownSections,
  POPULAR_SECTION,
  sectionCategory,
  UPLOADED_SECTION,
} from "@/views/plugins/sections";

const plugin = (id: string, extra: Partial<Plugin> = {}): Plugin => ({
  id,
  name: id,
  description: "d",
  category: "Developer",
  logoSlug: id,
  authMode: "pat_paste",
  authConfig: { mode: "pat_paste" },
  status: "not_connected",
  longevity: "permanent",
  oauthClientConfigured: false,
  fromMarketplace: false,
  selfUploaded: false,
  ...extra,
});

const ids = (plugins: Plugin[]) => plugins.map((p) => p.id);

describe("catalogSections", () => {
  it("leads with the featured plugins, then one section per category in the given order", () => {
    const sections = catalogSections(
      [
        plugin("zeta", { category: "Messaging" }),
        plugin("beta", { featured: true }),
        plugin("alpha"),
      ],
      ["Messaging", "Developer"],
    );
    expect(sections.map((s) => s.id)).toEqual([
      POPULAR_SECTION,
      categorySectionId("Messaging"),
      categorySectionId("Developer"),
    ]);
    expect(ids(sections[0].plugins)).toEqual(["beta"]);
    // A featured plugin still belongs to its category; rows there run A-Z.
    expect(ids(sections[2].plugins)).toEqual(["alpha", "beta"]);
  });

  it("has no Popular section when nothing is featured, and drops empty categories", () => {
    const sections = catalogSections([plugin("alpha")], ["Messaging", "Developer"]);
    expect(sections.map((s) => s.id)).toEqual([categorySectionId("Developer")]);
  });

  it("leaves what the owner added to the owner's scope", () => {
    const sections = catalogSections(
      [plugin("shipped"), plugin("mine", { selfUploaded: true }), plugin("theirs", { fromMarketplace: true })],
      ["Developer"],
    );
    expect(ids(sections[0].plugins)).toEqual(["shipped"]);
  });
});

describe("ownSections", () => {
  it("splits own connectors from community installs and omits the empty half", () => {
    const mine = plugin("mine", { selfUploaded: true });
    const theirs = plugin("theirs", { fromMarketplace: true });
    expect(ownSections([plugin("shipped"), theirs, mine]).map((s) => s.id)).toEqual([
      UPLOADED_SECTION,
      COMMUNITY_SECTION,
    ]);
    expect(ownSections([plugin("shipped"), theirs]).map((s) => s.id)).toEqual([COMMUNITY_SECTION]);
    expect(ownSections([plugin("shipped")])).toEqual([]);
  });
});

describe("section ids", () => {
  it("round-trips a category and never mistakes a curated section for one", () => {
    expect(sectionCategory(categorySectionId("Files & Photos"))).toBe("Files & Photos");
    expect(sectionCategory(POPULAR_SECTION)).toBeNull();
    // A category that happens to be called "popular" keeps its own section.
    expect(categorySectionId("popular")).not.toBe(POPULAR_SECTION);
  });

  it("names the section a plugin is listed under", () => {
    expect(homeSectionId(plugin("a", { category: "Messaging" }))).toBe(categorySectionId("Messaging"));
    expect(homeSectionId(plugin("b", { selfUploaded: true }))).toBe(UPLOADED_SECTION);
    expect(homeSectionId(plugin("c", { fromMarketplace: true }))).toBe(COMMUNITY_SECTION);
  });
});

describe("isInstalled", () => {
  it("keeps a broken connection and an unconnected owner-added plugin in the installed list", () => {
    expect(isInstalled(plugin("a"))).toBe(false);
    expect(isInstalled(plugin("b", { status: "connected" }))).toBe(true);
    expect(isInstalled(plugin("c", { status: "needs_reauth" }))).toBe(true);
    expect(isInstalled(plugin("d", { status: "error" }))).toBe(true);
    expect(isInstalled(plugin("e", { fromMarketplace: true }))).toBe(true);
    expect(isInstalled(plugin("f", { selfUploaded: true }))).toBe(true);
  });
});
