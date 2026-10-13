/** The icon each station wears in the HUD's places menu and in the reception's directory. */
import { ArrowUpDown, Coffee, ConciergeBell, Radar, Shirt, Sparkles, SquareTerminal, Star, Trophy, UserPlus, Users, type LucideIcon } from "lucide-react";
import type { StationIcon } from "./stations";

const ICONS: Record<StationIcon, LucideIcon> = {
  spawn: UserPlus, launch: SquareTerminal, reception: ConciergeBell, team: Users, wardrobe: Shirt, lead: Star, break: Coffee,
  elevator: ArrowUpDown, mission: Radar, studio: Sparkles, levels: Trophy,
};

export function StationGlyph({ icon, size = 16 }: { icon: StationIcon; size?: number }) {
  const Icon = ICONS[icon];
  return <Icon size={size} aria-hidden />;
}
