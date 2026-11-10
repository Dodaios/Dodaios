import {
  Eye,
  FilePenLine,
  Hand,
  NotebookPen,
  Shield,
  ShieldAlert,
  ShieldBan,
  WandSparkles,
  type LucideIcon,
} from "lucide-react";

/**
 * One glyph per permission STANCE, not per vendor spelling.
 *
 * The composer's permission pill draws whatever ladder the catalog delivers
 * (dodaios/agent_chat/permissions.py): the unified ladder on the front page
 * (`ask` / `accept-edits` / `plan` / `bypass`) and, for an IDE session, a
 * runner's own ids (`default`, `acceptEdits`, `bypassPermissions`, `auto`,
 * `read-only`, `full-access`, …). Several of those mean the same thing, so
 * they wear the same glyph — a person who learned "the pen means edits go
 * through" recognises it on every provider. Anything unknown falls back to
 * a plain shield so a new ladder entry is never blank.
 */
const GLYPHS: Record<string, LucideIcon> = {
  // Stops and asks before acting.
  ask: Hand,
  default: Hand,
  "approve-for-me": Hand,
  // Edits go through, everything else asks.
  "accept-edits": FilePenLine,
  acceptEdits: FilePenLine,
  // Nothing asks — the one stance that deserves a warning sign.
  bypass: ShieldAlert,
  bypassPermissions: ShieldAlert,
  "full-access": ShieldAlert,
  "skip-permissions": ShieldAlert,
  // Reads and plans, changes nothing.
  plan: NotebookPen,
  "read-only": Eye,
  // The runner decides on its own.
  auto: WandSparkles,
  // Never asks — and refuses what it would have asked about.
  dontAsk: ShieldBan,
};

export function permissionModeIcon(id: string): LucideIcon {
  return GLYPHS[id] ?? Shield;
}
