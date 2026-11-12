import {
  StanceAskIcon,
  StanceAutoIcon,
  StanceBypassIcon,
  StanceDenyIcon,
  StanceEditsIcon,
  StancePlanIcon,
  StanceReadOnlyIcon,
  StanceUnknownIcon,
} from "@/components/icons/stanceIcons";
import { describe, expect, it } from "vitest";

import { permissionModeIcon } from "./permissionIcons";

describe("permissionModeIcon", () => {
  it("maps every vendor spelling of a stance onto the stance's one glyph", () => {
    // Ask before acting — the unified ladder, Claude Code, and agy.
    expect(permissionModeIcon("ask")).toBe(StanceAskIcon);
    expect(permissionModeIcon("default")).toBe(StanceAskIcon);
    expect(permissionModeIcon("approve-for-me")).toBe(StanceAskIcon);
    // Edits go through.
    expect(permissionModeIcon("accept-edits")).toBe(StanceEditsIcon);
    expect(permissionModeIcon("acceptEdits")).toBe(StanceEditsIcon);
    // Nothing asks.
    expect(permissionModeIcon("bypass")).toBe(StanceBypassIcon);
    expect(permissionModeIcon("bypassPermissions")).toBe(StanceBypassIcon);
    expect(permissionModeIcon("full-access")).toBe(StanceBypassIcon);
    expect(permissionModeIcon("skip-permissions")).toBe(StanceBypassIcon);
    // The reading stances and the runner's own judgement.
    expect(permissionModeIcon("plan")).toBe(StancePlanIcon);
    expect(permissionModeIcon("read-only")).toBe(StanceReadOnlyIcon);
    expect(permissionModeIcon("auto")).toBe(StanceAutoIcon);
    expect(permissionModeIcon("dontAsk")).toBe(StanceDenyIcon);
  });

  it("gives an id it has never seen a plain shield, never nothing", () => {
    expect(permissionModeIcon("something-new")).toBe(StanceUnknownIcon);
    expect(permissionModeIcon("")).toBe(StanceUnknownIcon);
  });

  it("draws every stance in this app's own hand, not from the stock catalogue", () => {
    const ids = ["ask", "accept-edits", "bypass", "plan", "read-only", "auto", "dontAsk", "something-new"];
    for (const id of ids) {
      expect(permissionModeIcon(id).displayName).toMatch(/^Stance/);
    }
  });

  it("keeps the four stances of the unified ladder visually distinct", () => {
    const glyphs = ["ask", "accept-edits", "plan", "bypass"].map(permissionModeIcon);
    expect(new Set(glyphs).size).toBe(glyphs.length);
  });
});
