import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AgentMark } from "./AgentMark";
import cursorLogo from "@/assets/agents/cursor.svg?url";
import deepseekLogo from "@/assets/agents/deepseek.svg?url";
import kimiLogo from "@/assets/agents/kimi.svg?url";
import opencodeLogo from "@/assets/agents/opencode.svg?url";
import zaiLogo from "@/assets/agents/zai.svg?url";
import antigravityLogo from "@/assets/providers/antigravity.svg?url";
import claudeLogo from "@/assets/providers/claude.svg?url";
import openaiLogo from "@/assets/providers/openai.svg?url";
import xaiLogo from "@/assets/providers/xai.svg?url";

afterEach(cleanup);

/**
 * How a brand mark survives BOTH themes.
 *
 * Every logo that ships with the app was drawn for the dark product this
 * started as, and on the light theme the restore screen showed seven terminals
 * with no sign of which CLI each was running (maintainer, 2026-08-11). The
 * marks are not all broken the same way, so what is pinned here is the routing:
 * which file is drawn in the theme's ink, which one keeps its colours and
 * gets the dark ground it was painted against, and which one is left alone.
 *
 * `data-ground` and `data-logo` are asserted rather than the DOM shape, because
 * an ink mark is a CSS mask and jsdom does not model mask properties — a test
 * that looked for an <img> would call the working marks broken.
 */
function mark(agent: string): HTMLElement {
  return screen.getByTestId(`agent-mark-${agent}`);
}

describe("AgentMark", () => {
  it.each([
    ["codex", openaiLogo],
    ["grok-build", xaiLogo],
    ["cursor", cursorLogo],
    ["deepseek-harness", deepseekLogo],
    ["kimi", kimiLogo],
    ["opencode", opencodeLogo],
    ["glm", zaiLogo],
  ])("draws the single-colour %s glyph in the theme's own ink", (agent, file) => {
    // A mono glyph is a mask over the text ink: neutral monochrome that follows
    // light/dark by itself, never a palette colour of ours.
    render(<AgentMark agent={agent} label={agent} />);
    expect(mark(agent).getAttribute("data-ground")).toBe("ink");
    expect(mark(agent).getAttribute("data-logo")).toBe(file);
    // The <img> is what made a mono mark invisible on paper; it must be gone.
    expect(mark(agent).querySelector("img")).toBeNull();
  });

  it.each([
    ["claude", claudeLogo],
    ["antigravity", antigravityLogo],
  ])("draws the %s mark in its own colours, untouched", (agent, file) => {
    // A full-colour mark on a transparent ground reads on both themes; it is
    // shown exactly as the vendor drew it rather than flattened to a silhouette.
    render(<AgentMark agent={agent} label={agent} />);
    expect(mark(agent).getAttribute("data-ground")).toBe("any");
    expect(mark(agent).querySelector("img")?.getAttribute("src")).toBe(file);
    expect(mark(agent).className).not.toContain("bg-scrim");
  });

  it("never points at an unsourced public copy", () => {
    for (const agent of ["claude", "codex", "cursor", "glm", "grok-build", "kimi", "opencode"]) {
      const { unmount } = render(<AgentMark agent={agent} label={agent} />);
      expect(mark(agent).getAttribute("data-logo")).not.toMatch(/provider-logos|agent-logos/);
      unmount();
    }
  });

  it("does not guess a ground for a logo the user uploaded", () => {
    // We know nothing about the file; a canvas added on a guess could hide a
    // mark that was perfectly legible on its own.
    render(
      <AgentMark agent="mycli" label="My CLI" logoUrl="/uploads/mine.svg" />,
    );
    expect(mark("mycli").getAttribute("data-ground")).toBe("any");
    expect(mark("mycli").querySelector("img")?.getAttribute("src")).toBe(
      "/uploads/mine.svg",
    );
  });

  it("falls back to a monogram for a CLI with no mark at all", () => {
    render(<AgentMark agent="mystery" label="Mystery CLI" />);
    expect(mark("mystery").getAttribute("data-ground")).toBe("none");
    expect(mark("mystery").querySelector("img")).toBeNull();
    expect(mark("mystery").textContent).toBe("MY");
  });

  it("keeps the plain variant tile-free for colour and ink marks alike", () => {
    const { unmount } = render(
      <AgentMark agent="claude" label="Claude Code" variant="plain" />,
    );
    expect(mark("claude").className).not.toContain("bg-scrim");
    unmount();

    render(<AgentMark agent="kimi" label="Kimi" variant="plain" />);
    expect(mark("kimi").className).not.toContain("bg-scrim");
  });
});
