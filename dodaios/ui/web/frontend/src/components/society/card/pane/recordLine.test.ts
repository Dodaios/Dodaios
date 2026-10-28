import { describe, expect, it } from "vitest";

import en from "@/i18n/locales/society/en.json";
import de from "@/i18n/locales/society/de.json";
import { recordLine } from "./OverviewTab";

type Dict = Record<string, unknown>;
const lookup = (dict: Dict) => (key: string) =>
  String(key.split(".").reduce<unknown>((node, part) => (node as Dict | undefined)?.[part], dict) ?? key);
const stats = (runs: number) => ({ runs, totalCostUsd: 1.2, spentTodayUsd: 0, lastActiveMs: null });

describe("the agent's record line", () => {
  it("says one run, not one runs", () => {
    expect(recordLine(lookup(en as Dict), "en", { stats: stats(1) }, "12 Oct")).toBe("1 run · $1.20 spent · last active 12 Oct");
    expect(recordLine(lookup(en as Dict), "en", { stats: stats(3) }, "12 Oct")).toBe("3 runs · $1.20 spent · last active 12 Oct");
    expect(recordLine(lookup(de as Dict), "de", { stats: stats(1) }, "12. Okt.")).toBe("1 Lauf · $1.20 ausgegeben · zuletzt aktiv 12. Okt.");
  });

  it("shows no money on a subscription seat", () => {
    const line = recordLine(lookup(en as Dict), "en", { stats: stats(2), billedPerToken: false }, "12 Oct");
    expect(line).toBe("2 runs · last active 12 Oct");
  });
});
