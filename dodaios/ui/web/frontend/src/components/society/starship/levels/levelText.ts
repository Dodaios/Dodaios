/**
 * Words for the level UI: rank, reward and source names, limits and log
 * lines in the UI language (`ship.levels.*`, `ship.rank.*`, `ship.deck.*`).
 * A source the ledger still carries from the office tower reads in its old
 * words; anything unknown reads as "Earned XP", never as a raw key.
 */
import { useMemo } from "react";
import { useT } from "@/i18n";
import { useRunLocale } from "@/components/runs/format";
import { isXpSource } from "../../progression/levelCatalog";
import type { LogLine, RuleLimit } from "./levelModel";

/** The office tower's sources, still in old ledgers (`ship.levels.legacy_source.*`). */
export const LEGACY_SOURCES = ["floor_discovered", "dog_petted", "dog_treat", "arcade_round", "arcade_record", "team_meeting"] as const;

export function fill(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (all, key: string) => (key in vars ? String(vars[key]) : all));
}

/** The i18n key a ledger source reads with. */
export function sourceKey(source: string): string {
  if (isXpSource(source)) return `ship.levels.source.${source}`;
  if ((LEGACY_SOURCES as readonly string[]).includes(source)) return `ship.levels.legacy_source.${source}`;
  return "ship.levels.legacy_source.other";
}

const DAY_MS = 86_400_000;

export function useLevelText() {
  const t = useT();
  const locale = useRunLocale();
  return useMemo(() => {
    const num = (n: number) => n.toLocaleString(locale);
    const rank = (id: string) => t(`ship.rank.${id}`);
    const reward = (id: string) => t(`ship.levels.reward.${id}`);
    const place = (destination: string) => (destination === "home" ? t("ship.levels.home") : reward(`destination_${destination}`));
    const duration = (s: number) => (s < 60 ? fill(t("ship.levels.earn.seconds"), { n: s }) : fill(t("ship.levels.earn.minutes"), { n: Math.round(s / 60) }));
    return {
      t, num, rank, reward, place,
      level: (n: number) => fill(t("ship.levels.level"), { n }),
      xpToGo: (n: number) => fill(t("ship.levels.to_go"), { n: num(n) }),
      source: (source: string) => t(sourceKey(source)),
      limit: (limit: RuleLimit): string => {
        if (limit.kind === "once_day") return t("ship.levels.earn.once_day");
        if (limit.kind === "once_deck") return t("ship.levels.earn.once_deck");
        if (limit.kind === "none") return "";
        const parts: string[] = [];
        if (limit.cooldownS > 0) parts.push(fill(t("ship.levels.earn.every"), { t: duration(limit.cooldownS) }));
        if (limit.dailyCap > 0) parts.push(fill(t("ship.levels.earn.per_day"), { n: num(limit.dailyCap) }));
        return parts.join(", ");
      },
      logLine: (line: LogLine): string => {
        switch (line.kind) {
          case "promoted": return fill(t("ship.levels.log_promoted"), { rank: rank(line.rank) });
          case "level": return fill(t("ship.levels.log_level"), { n: line.level });
          case "warp": return fill(t("ship.levels.log_warp"), { place: place(line.destination) });
          case "deck": return fill(t("ship.levels.log_deck"), { deck: t(`ship.deck.${line.deck}`) });
          default: return t(sourceKey(line.source));
        }
      },
      /** A log time: the clock today, "Yesterday", else the date. */
      when: (tsMs: number, nowMs = Date.now()): string => {
        const at = new Date(tsMs), now = new Date(nowMs);
        const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
        if (tsMs >= startOfToday) return at.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
        if (tsMs >= startOfToday - DAY_MS) return t("ship.levels.yesterday");
        return at.toLocaleDateString(locale, { day: "numeric", month: "short" });
      },
    };
  }, [t, locale]);
}

export type LevelText = ReturnType<typeof useLevelText>;
