import type { LucideIcon } from "lucide-react";

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

/**
 * One glyph per permission STANCE, not per vendor spelling.
 *
 * The composer's permission pill draws whatever ladder the catalog delivers
 * (dodaios/agent_chat/permissions.py): the unified ladder on the front page
 * (`ask` / `accept-edits` / `plan` / `bypass`) and, for an IDE session, a
 * runner's own ids (`default`, `acceptEdits`, `bypassPermissions`, `auto`,
 * `read-only`, `full-access`, …). Several of those mean the same thing, so
 * they wear the same glyph — a person who learned "the pencil means edits go
 * through" recognises it on every provider. Anything unknown falls back to
 * a plain shield so a new ladder entry is never blank.
 *
 * The glyphs are this app's own drawings (icons/stanceIcons.tsx), one family
 * at one weight, not picks from a stock catalogue.
 */
const GLYPHS: Record<string, LucideIcon> = {
  // Stops and asks before acting.
  ask: StanceAskIcon,
  default: StanceAskIcon,
  "approve-for-me": StanceAskIcon,
  // Edits go through, everything else asks.
  "accept-edits": StanceEditsIcon,
  acceptEdits: StanceEditsIcon,
  // Nothing asks — the one stance that deserves a warning sign.
  bypass: StanceBypassIcon,
  bypassPermissions: StanceBypassIcon,
  "full-access": StanceBypassIcon,
  "skip-permissions": StanceBypassIcon,
  // Reads and plans, changes nothing.
  plan: StancePlanIcon,
  "read-only": StanceReadOnlyIcon,
  // The runner decides on its own.
  auto: StanceAutoIcon,
  // Never asks — and refuses what it would have asked about.
  dontAsk: StanceDenyIcon,
};

export function permissionModeIcon(id: string): LucideIcon {
  return GLYPHS[id] ?? StanceUnknownIcon;
}
