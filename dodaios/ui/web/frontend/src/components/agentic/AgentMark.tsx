import { useState } from "react";
import { SquareTerminal } from "lucide-react";

import { cn } from "@/lib/utils";

import antigravityLogo from "@/assets/providers/antigravity.svg?url";
import claudeLogo from "@/assets/providers/claude.svg?url";
import openaiLogo from "@/assets/providers/openai.svg?url";
import xaiLogo from "@/assets/providers/xai.svg?url";
import cursorLogo from "@/assets/agents/cursor.svg?url";
import deepseekLogo from "@/assets/agents/deepseek.svg?url";
import kimiLogo from "@/assets/agents/kimi.svg?url";
import opencodeLogo from "@/assets/agents/opencode.svg?url";
import zaiLogo from "@/assets/agents/zai.svg?url";

/**
 * What ground a brand file needs in order to be legible.
 *
 * Every file comes from a ledgered source (`src/assets/providers/LOGOS.md`,
 * `src/assets/agents/LOGOS.md`) and is drawn unmodified. A mark is shown either
 * in its own colours or in neutral monochrome, never recoloured.
 *
 * * `ink` — a single-colour glyph. It is drawn as a MASK over the current
 *   text ink, so it follows the theme by itself: near-white on the dark app,
 *   near-black on paper, from one asset and with no theme prop threaded
 *   through the tree.
 * * `dark` — a full-colour lockup whose own background is white or near-white.
 *   On paper those shapes ARE the paper, so it keeps its colours and gets a
 *   constant dark canvas: the ground it was drawn on. No shipped mark needs
 *   it today; it stays for that shape of logo.
 * * `any` — a full-colour mark on a transparent ground (Claude's spark,
 *   Antigravity's arch) that reads on either theme in its own colours.
 */
type LogoGround = "ink" | "dark" | "any";

interface LogoAsset {
  url: string;
  ground: LogoGround;
}

const AGENT_LOGOS: Record<string, LogoAsset> = {
  antigravity: { url: antigravityLogo, ground: "any" },
  claude: { url: claudeLogo, ground: "any" },
  codex: { url: openaiLogo, ground: "ink" },
  cursor: { url: cursorLogo, ground: "ink" },
  "deepseek-harness": { url: deepseekLogo, ground: "ink" },
  glm: { url: zaiLogo, ground: "ink" },
  "grok-build": { url: xaiLogo, ground: "ink" },
  kimi: { url: kimiLogo, ground: "ink" },
  opencode: { url: opencodeLogo, ground: "ink" },
};

/**
 * The shipped brand file for an agent and the ground it needs, or null for an
 * agent without one. For drawing the mark where no DOM exists (a canvas).
 */
export function agentLogoAsset(agent: string): { url: string; ground: LogoGround } | null {
  return AGENT_LOGOS[agent] ?? null;
}

interface AgentMarkProps {
  agent: string;
  label: string;
  className?: string;
  size?: "sm" | "md" | "lg";
  /**
   * An image to draw instead of the built-in table's — the mark a user uploaded
   * for a CLI of their own.
   *
   * Passed in rather than looked up, because this component cannot know it: the
   * table above is a fixed list of brands that ship with the app, and an entry
   * added at runtime has no place in it. An entry with no logo (and every
   * shipped one) leaves this undefined and the table decides as before.
   *
   * An upload is treated as `any`: we know nothing about the file, and a canvas
   * added on a guess could hide a mark that was perfectly fine on its own.
   */
  logoUrl?: string;
  /**
   * How much of a mark this is.
   *
   * `boxed` is the identity badge: a framed tile, for the places that are ABOUT
   * which agent this is — a pane header, an agent picker. `plain` is the same
   * glyph with the tile taken away, for a list of conversations, where the mark
   * is a hint beside a title rather than the subject of the row. A framed tile
   * repeated down forty rows turns a reading list into a grid of boxes.
   *
   * A `dark`-ground lockup is the one exception: it cannot be shown without
   * something to sit on, so it keeps a small canvas even when plain. Better a
   * chip in a list than a mark nobody can identify.
   */
  variant?: "boxed" | "plain";
}

/**
 * A registry-safe visual identity for a terminal agent.
 *
 * Known products use local, offline brand assets. Unknown registry entries get
 * a neutral monogram, so adding another CLI never produces a broken image. The
 * plain terminal is a capability rather than a brand and therefore uses the
 * system-terminal glyph.
 */
export function AgentMark({
  agent,
  label,
  className,
  size = "md",
  variant = "boxed",
  logoUrl,
}: AgentMarkProps) {
  /*
   * WHICH logo failed, not merely "one did".
   *
   * A boolean would stick: a user who replaces a broken upload with a working
   * one keeps seeing the monogram, because the component is the same instance
   * and its flag never clears. Storing the URL that failed makes the next one a
   * fresh attempt without an effect to keep in step.
   */
  const [failedLogo, setFailedLogo] = useState<string | null>(null);
  const asset: LogoAsset | undefined = logoUrl
    ? { url: logoUrl, ground: "any" }
    : AGENT_LOGOS[agent];
  const failed = failedLogo != null && failedLogo === asset?.url;
  const monogram = label.trim().slice(0, 2).toUpperCase() || "?";
  const plain = variant === "plain";
  const drawn = agent !== "shell" && asset && !failed;
  /*
   * A mask has no load event, so the failure path above cannot cover it. That
   * is not a gap: `ink` is only ever an asset that ships inside the bundle,
   * while the uploads the fallback exists for are always drawn as an image.
   */
  const inked = drawn && asset.ground === "ink";
  const canvased = drawn && asset.ground === "dark";
  const sizeClass = plain
    ? size === "sm"
      ? "h-4 w-4"
      : "h-5 w-5"
    : size === "sm"
      ? "h-7 w-7 rounded-[5px]"
      : size === "lg"
        ? "h-11 w-11 rounded-control"
        : "h-9 w-9 rounded-control";
  const glyphClass = plain
    ? "h-full w-full"
    : size === "sm"
      ? "h-3.5 w-3.5"
      : size === "lg"
        ? "h-6 w-6"
        : "h-5 w-5";

  return (
    <span
      data-testid={`agent-mark-${agent}`}
      /* Which file is being drawn and on what, stated on the element rather
         than inferred from it: an `ink` mark is a CSS mask, and a mask lives in
         a style property jsdom does not model, so a test that reached for the
         <img> would report "no logo" for the marks that work best. */
      data-logo={drawn ? asset.url : undefined}
      data-ground={asset?.ground ?? "none"}
      aria-hidden="true"
      className={cn(
        "inline-flex shrink-0 items-center justify-center overflow-hidden text-micro font-bold tracking-tight text-muted-foreground",
        // The tile, and the brightness that goes with being one. Without it the
        // glyph sits at the weight of the text it accompanies, which is the
        // point of `plain`.
        plain
          ? canvased
            ? "rounded-[4px] bg-scrim/95 p-px"
            : "opacity-70"
          : canvased
            ? "border border-border bg-scrim/95"
            : "border border-border bg-background",
        sizeClass,
        className,
      )}
    >
      {agent === "shell" ? (
        <SquareTerminal
          className={plain || size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4"}
        />
      ) : inked ? (
        /*
         * `bg-foreground` rather than `bg-current`: the wrapper's ink is the
         * muted channel, which is right for the monogram beside a title and
         * too faint for a brand mark. Neutral monochrome either way.
         */
        <span
          className={cn("block bg-foreground", glyphClass)}
          style={{
            WebkitMaskImage: `url("${asset.url}")`,
            maskImage: `url("${asset.url}")`,
            WebkitMaskRepeat: "no-repeat",
            maskRepeat: "no-repeat",
            WebkitMaskPosition: "center",
            maskPosition: "center",
            WebkitMaskSize: "contain",
            maskSize: "contain",
          }}
        />
      ) : drawn ? (
        <img
          src={asset.url}
          alt=""
          // Plain fills its box: there is no tile to sit inside, so the glyph
          // IS the mark and shrinking it further would leave a speck.
          className={cn("block object-contain", glyphClass)}
          onError={() => setFailedLogo(asset.url)}
        />
      ) : (
        <span className="font-mono">{monogram}</span>
      )}
    </span>
  );
}
