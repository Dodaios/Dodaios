/**
 * One colour and one glyph per kind of memory. The colours are calm system
 * hues that read on both themes; every surface that shows a kind (sidebar,
 * row, inspector, file) takes them from here.
 */
import {
  CalendarClock,
  Compass,
  Heart,
  type LucideIcon,
  Lightbulb,
  Rocket,
  ScrollText,
  Sparkles,
  UserRound,
  Users,
} from "lucide-react";
import type { MemoryKind } from "@/lib/personalMemoryApi";

export interface KindStyle {
  icon: LucideIcon;
  /** An `H S% L%` triple, used as `hsl(...)` with or without alpha. */
  hue: string;
}

export const KIND_STYLE: Record<MemoryKind, KindStyle> = {
  profile: { icon: UserRound, hue: "211 100% 58%" },
  preference: { icon: Heart, hue: "340 82% 60%" },
  relationship: { icon: Users, hue: "28 95% 56%" },
  project: { icon: Rocket, hue: "266 70% 64%" },
  procedural: { icon: ScrollText, hue: "142 58% 46%" },
  episode: { icon: Sparkles, hue: "45 95% 52%" },
  reference: { icon: Lightbulb, hue: "187 72% 46%" },
  ephemeral: { icon: CalendarClock, hue: "220 9% 56%" },
};

export const IN_MIND_STYLE: KindStyle = { icon: Compass, hue: "211 100% 58%" };

export function kindColor(kind: MemoryKind, alpha = 1): string {
  return `hsl(${KIND_STYLE[kind].hue} / ${alpha})`;
}
