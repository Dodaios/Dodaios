/**
 * The icon a starter and an area wear in the gallery. The catalogue names
 * icons as plain words, so the data stays free of UI code; an unknown name
 * falls back to a neutral mark rather than an empty tile.
 */
import {
  Activity, BadgeCheck, BookOpenText, Bot, Bug, CalendarCheck, CalendarClock, Code2, Coffee, Feather,
  FileText, FlaskConical, GitPullRequest, GraduationCap, House, Inbox, Languages, LayoutGrid, ListChecks,
  Mail, MailCheck, Map as MapIcon, Megaphone, Music, PenLine, Radar, Rocket, ScrollText, Search, Server, Sunrise,
  Telescope, Wallet, type LucideIcon,
} from "lucide-react";
import type { AreaFilter } from "./starterFilters";

const STARTER_ICONS: Readonly<Record<string, LucideIcon>> = {
  "git-pull-request": GitPullRequest,
  bug: Bug,
  "flask-conical": FlaskConical,
  "scroll-text": ScrollText,
  search: Search,
  radar: Radar,
  "book-open-text": BookOpenText,
  "badge-check": BadgeCheck,
  inbox: Inbox,
  "calendar-check": CalendarCheck,
  "calendar-clock": CalendarClock,
  "mail-check": MailCheck,
  "pen-line": PenLine,
  megaphone: Megaphone,
  "file-text": FileText,
  languages: Languages,
  rocket: Rocket,
  server: Server,
  "list-checks": ListChecks,
  wallet: Wallet,
  sunrise: Sunrise,
  map: MapIcon,
  house: House,
  "graduation-cap": GraduationCap,
  music: Music,
};

const AREA_ICONS: Readonly<Record<AreaFilter, LucideIcon>> = {
  all: LayoutGrid,
  coding: Code2,
  research: Telescope,
  inbox: Mail,
  writing: Feather,
  ops: Activity,
  personal: Coffee,
};

export function StarterIcon({ name, className }: { name: string; className?: string }) {
  const Icon = STARTER_ICONS[name] ?? Bot;
  return <Icon className={className} aria-hidden />;
}

export function AreaIcon({ area, className }: { area: AreaFilter; className?: string }) {
  const Icon = AREA_ICONS[area] ?? LayoutGrid;
  return <Icon className={className} aria-hidden />;
}

/** Every icon name the gallery can draw (the data test checks the catalogue against it). */
export const KNOWN_STARTER_ICONS: readonly string[] = Object.keys(STARTER_ICONS);
