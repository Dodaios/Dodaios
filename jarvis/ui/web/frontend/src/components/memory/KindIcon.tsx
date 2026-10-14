import {
  BookMarked,
  Brain,
  CalendarDays,
  FileText,
  FolderKanban,
  LayoutTemplate,
  Lightbulb,
  Settings2,
  Share2,
  Shapes,
  User,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { MemoryKind } from "@/lib/memoryApi";

const ICONS: Record<MemoryKind, LucideIcon> = {
  entity: Shapes,
  person: User,
  project: FolderKanban,
  concept: Lightbulb,
  session: CalendarDays,
  note: FileText,
  memory: Brain,
  profile: UserRound,
  shared: Share2,
  system: Settings2,
  template: LayoutTemplate,
};

/** One quiet glyph per page kind; colour stays with the surrounding ink. */
export function KindIcon({ kind, className }: { kind: MemoryKind | null | undefined; className?: string }) {
  const Icon = (kind && ICONS[kind]) || BookMarked;
  return <Icon className={cn("h-4 w-4 shrink-0", className)} aria-hidden />;
}
