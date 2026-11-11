import { useEffect } from "react";

import { useT } from "@/i18n";

import { useStatusLightStore, watchStatusLight } from "./statusLightStore";
import { StatusGroup, StatusTroubleGroup, goToStatusRow } from "./statusRows";

/** How many rows of a kind the column lists before it only counts the rest. */
const NEEDS_SHOWN = 5;
const RUNNING_SHOWN = 3;

/**
 * What waits on the person and what runs, listed in the sidebar beside the
 * conversation (`statusLightStore`, kept fresh by the watcher this list
 * starts). Nothing shows while all is quiet.
 */
export function SidebarStatus() {
  const t = useT();
  const light = useStatusLightStore((s) => s.light);
  useEffect(() => watchStatusLight(), []);
  const needs = light?.needs_you ?? [];
  const running = light?.running ?? [];
  const trouble = light?.trouble ?? [];
  const findings = light?.findings ?? [];
  if (needs.length === 0 && running.length === 0 && trouble.length === 0 && findings.length === 0) return null;

  return (
    <section aria-label={t("status_light.title")} data-testid="sidebar-status" className="mt-3 border-t border-border px-2 pb-3 pt-4">
      <StatusGroup title={t("status_light.needs_heading")} rows={needs} onGo={goToStatusRow} testId="sidebar-status-needs" max={NEEDS_SHOWN} />
      <StatusGroup title={t("status_light.running_heading")} rows={running} running onGo={goToStatusRow} testId="sidebar-status-running" max={RUNNING_SHOWN} />
      <StatusTroubleGroup trouble={trouble} findings={findings} testId="sidebar-status-trouble" />
    </section>
  );
}
