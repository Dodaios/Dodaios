/**
 * Reception: the office's directory. Four tabs — everyone on the floor (show
 * on the map, open, the agents view), every place of the floor (open it, or
 * walk there), the complete controls guide (from officeControls, searchable)
 * and the map's settings (officeSettings). H opens it on the controls tab
 * from anywhere, so nobody has to find the desk to learn the keys.
 *
 * Nothing is created here: new agents come from the spawn terminal.
 */
import { useState } from "react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, ChevronRight, Footprints, Search } from "lucide-react";
import { useT } from "@/i18n";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { SocietyAgent } from "../data";
import { countStates, type OfficeLayout } from "./officeLayout";
import { useOfficeStore, type OfficeFloor } from "./officeStore";
import { agentPositions } from "./walkerRegistry";
import { isReception, stationsFor, type Station } from "./stations";
import { AgentFace } from "./AgentFace";
import { StationGlyph } from "./stationIcons";
import { stationAction, stationLabel } from "./stationText";
import { arrowCap, CONTROL_GROUPS, controlsFor, mouseGesture, type ArrowKey, type OfficeControl } from "./officeControls";
import { useOfficeSettings, useReceptionTab, type ReceptionTab } from "./officeSettings";
import type { OfficeActions } from "./OfficePanels";
import "./reception.css";

const TABS: readonly ReceptionTab[] = ["agents", "places", "controls", "settings"];

const ARROW_ICON: Record<ArrowKey, typeof ArrowUp> = { up: ArrowUp, down: ArrowDown, left: ArrowLeft, right: ArrowRight };

/** How a key cap reads aloud and in the search ("Space", "Arrow up", "Drag"). */
function useCapLabel() {
  const t = useT();
  return (cap: string) => {
    const gesture = mouseGesture(cap);
    if (gesture) return t(`society.office.guide.mouse_${gesture}`);
    const arrow = arrowCap(cap);
    if (arrow) return t(`society.office.guide.key_${arrow}`);
    return cap === "Space" ? t("society.office.guide.key_space") : cap;
  };
}

export function KeyCaps({ control }: { control: Pick<OfficeControl, "keys"> }) {
  const t = useT();
  const label = useCapLabel();
  return (
    <span className="office-keys">
      {control.keys.map((alt, i) => (
        <span key={i} className="office-keys-alt">
          {i > 0 && <span className="office-keys-or">{t("society.office.guide.or")}</span>}
          {alt.map((cap, j) => {
            if (cap === "+") return <span key={j} className="office-keys-plus" aria-hidden>+</span>;
            if (mouseGesture(cap)) return <kbd key={j} className="office-key" data-mouse>{label(cap)}</kbd>;
            const arrow = arrowCap(cap);
            if (arrow) {
              const Icon = ARROW_ICON[arrow];
              return <kbd key={j} className="office-key" aria-label={label(cap)}><Icon size={12} aria-hidden /></kbd>;
            }
            return <kbd key={j} className="office-key">{label(cap)}</kbd>;
          })}
        </span>
      ))}
    </span>
  );
}

/**
 * Arrow keys inside the places list: up and down move through the rows, right
 * goes to a row's "walk there" and left back to the row, Home and End jump.
 * Returns the button to focus, or null when the key is not one of them.
 */
export function placesKeyTarget(list: HTMLElement, from: Element | null, key: string): HTMLElement | null {
  const rows = [...list.querySelectorAll<HTMLElement>("[data-place-open]")];
  if (rows.length === 0) return null;
  const row = from instanceof HTMLElement ? from.closest<HTMLElement>("[data-place-row]") : null;
  const index = row ? rows.findIndex((button) => row.contains(button)) : -1;
  if (key === "Home") return rows[0]!;
  if (key === "End") return rows[rows.length - 1]!;
  if (key === "ArrowDown") return rows[index < 0 ? 0 : Math.min(rows.length - 1, index + 1)]!;
  if (key === "ArrowUp") return rows[index < 0 ? rows.length - 1 : Math.max(0, index - 1)]!;
  if (!row) return null;
  if (key === "ArrowRight") return row.querySelector<HTMLElement>("[data-place-walk]");
  if (key === "ArrowLeft") return row.querySelector<HTMLElement>("[data-place-open]");
  return null;
}

/**
 * Every place of the floor as a real button: open it from here, or walk
 * there. Also the keyboard path to every station. The rooms' stations come
 * first, then the team studios' boards under their team's name.
 */
export function PlacesList({ layout, onPicked, withReception = false }: {
  layout: OfficeLayout; onPicked?: () => void;
  /** The reception itself is a place too, except in its own directory. */
  withReception?: boolean;
}) {
  const t = useT();
  const store = useOfficeStore;
  const stations = stationsFor(layout).filter((station) => withReception || !isReception(station.selection));
  const groups = [
    { id: "places", label: t("society.office.hud_places"), rows: stations.filter((station) => station.selection.kind !== "team") },
    { id: "teams", label: t("society.office.places_teams"), rows: stations.filter((station) => station.selection.kind === "team") },
  ].filter((group) => group.rows.length > 0);
  const point = (station: Station | null) => store.getState().setHover(station ? station.selection : null);
  // Whatever closes the list must not leave a place lit in the world.
  const done = () => { point(null); onPicked?.(); };
  return (
    <div className="grid gap-2" data-places
      onKeyDown={(event) => {
        const target = placesKeyTarget(event.currentTarget, document.activeElement, event.key);
        if (!target) return;
        // The arrows belong to the list while focus is in it; they must not walk the character too.
        event.preventDefault();
        event.stopPropagation();
        target.focus();
        target.scrollIntoView?.({ block: "nearest" });
      }}>
      {groups.map((group) => (
        <section key={group.id} className="grid gap-0.5" aria-label={group.label}>
          {groups.length > 1 && <h3 className="px-2 pt-1 text-xs font-semibold text-muted-foreground">{group.label}</h3>}
          <ul className="grid list-none gap-0.5 p-0">
            {group.rows.map((station) => {
              const name = stationLabel(station, t);
              const action = stationAction(station, t);
              return (
                <li key={station.key} data-place-row className="flex items-center gap-1 rounded-md hover:bg-secondary focus-within:bg-secondary"
                  onPointerEnter={() => point(station)} onPointerLeave={() => point(null)}>
                  <button type="button" data-place-open className="flex min-w-0 flex-1 items-center gap-3 rounded-md px-2 py-1.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label={`${name}: ${action}`}
                    onFocus={() => point(station)} onBlur={() => point(null)}
                    onClick={() => { done(); store.getState().select(station.selection); }}>
                    <span aria-hidden className="grid size-7 shrink-0 place-items-center rounded-md border border-border bg-background text-muted-foreground"><StationGlyph icon={station.icon} size={15} /></span>
                    <span className="grid min-w-0 gap-0.5">
                      <span className="truncate text-sm font-medium text-foreground">{name}</span>
                      <span className="truncate text-xs text-muted-foreground">{action}</span>
                    </span>
                    <ChevronRight size={14} aria-hidden className="ml-auto shrink-0 text-muted-foreground" />
                  </button>
                  <button type="button" data-place-walk className="mr-1 inline-flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-background hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label={t("society.office.guide.place_walk_label").replace("{0}", name)} title={t("society.office.guide.place_walk")}
                    onClick={() => { done(); store.getState().select(null); store.getState().requestWalk(station.approach); }}>
                    <Footprints size={15} aria-hidden />
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}

function AgentsTab({ agents, actions }: { agents: readonly SocietyAgent[]; actions: OfficeActions }) {
  const t = useT();
  const counts = countStates(agents);
  const show = (agent: SocietyAgent) => {
    const store = useOfficeStore.getState();
    const where = agentPositions.get(agent.agentId);
    if (where) store.focusOn(where);
    store.select({ kind: "agent", id: agent.agentId });
  };
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          {[t("society.office.count_working").replace("{0}", String(counts.working)), t("society.office.count_waiting").replace("{0}", String(counts.waiting)),
            t("society.office.count_idle").replace("{0}", String(counts.idle))].join(" · ")}
        </p>
        <Button type="button" size="sm" variant="outline" onClick={actions.onOpenLedger}>{t("society.office.manage_action")}</Button>
      </div>
      {agents.length === 0 ? <p className="rounded-lg border border-dashed border-border p-5 text-sm text-muted-foreground">{t("society.office.manage_empty")}</p> : (
        <ul className="grid max-h-[22rem] list-none gap-0.5 overflow-y-auto p-0">
          {agents.map((agent) => (
            <li key={agent.agentId} className="flex items-center gap-3 rounded-md px-2 py-1.5 hover:bg-secondary/60">
              <AgentFace agent={agent} />
              <span className="grid min-w-0 flex-1">
                <span className="truncate text-sm font-medium" title={agent.name}>{agent.name}</span>
                {(agent.title || agent.providerLabel) && <span className="truncate text-xs text-muted-foreground">{agent.title || agent.providerLabel}</span>}
              </span>
              <span className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
                <i className="office-dot" data-state={agent.state} aria-hidden />{t(`society.office.state_${agent.state}`)}
              </span>
              <Button type="button" size="sm" variant="ghost" aria-label={t("society.office.show_agent").replace("{0}", agent.name)}
                onClick={() => show(agent)}>{t("society.office.action_show")}</Button>
              <Button type="button" size="sm" variant="ghost" aria-label={t("society.office.open_agent").replace("{0}", agent.name)}
                onClick={() => actions.onOpenAgent(agent.agentId)}>{t("society.office.action_open")}</Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ControlsTab({ floor }: { floor: OfficeFloor }) {
  const t = useT();
  const label = useCapLabel();
  const [query, setQuery] = useState("");
  const needle = query.trim().toLocaleLowerCase();
  // A search matches the action's words, or names one of its keys exactly ("e", "shift").
  const matches = (control: OfficeControl) => !needle
    || t(`society.office.guide.ctl_${control.id}`).toLocaleLowerCase().includes(needle)
    || control.keys.flat().some((cap) => cap !== "+" && label(cap).toLocaleLowerCase() === needle);
  const groups = CONTROL_GROUPS
    .map((group) => ({ group, controls: controlsFor(group, floor).filter(matches) }))
    .filter((g) => g.controls.length > 0);
  return (
    <div className="grid gap-3">
      <div className="relative">
        <Search size={15} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input type="search" className="pl-9" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("society.office.guide.search")}
          aria-label={t("society.office.guide.search")}
          onKeyDown={(e) => { if (e.key === "Escape" && query) { e.preventDefault(); e.stopPropagation(); setQuery(""); } }} />
      </div>
      {groups.length === 0 ? <p className="py-4 text-center text-sm text-muted-foreground" role="status">{t("society.office.guide.search_empty")}</p> : (
        <div className="grid gap-4">
          {groups.map(({ group, controls }) => (
            <section key={group} className="grid gap-1" aria-label={t(`society.office.guide.group_${group}`)}>
              <h3 className="text-xs font-semibold text-muted-foreground">{t(`society.office.guide.group_${group}`)}</h3>
              <ul className="grid list-none p-0">
                {controls.map((control) => (
                  <li key={control.id} className="flex items-center justify-between gap-3 border-t border-border/60 py-1.5 text-sm first:border-t-0">
                    <span className="min-w-0">{t(`society.office.guide.ctl_${control.id}`)}</span>
                    <KeyCaps control={control} />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
      <p className="flex items-center gap-2 text-xs text-muted-foreground"><kbd className="office-key">H</kbd>{t("society.office.guide.tip_guide")}</p>
    </div>
  );
}

function SettingRow({ title, hint, children }: { title: string; hint: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 p-3">
      <span className="grid min-w-0 gap-0.5">
        <span className="text-sm font-medium">{title}</span>
        <span className="text-xs text-muted-foreground">{hint}</span>
      </span>
      {children}
    </div>
  );
}

function SettingsTab() {
  const t = useT();
  const settings = useOfficeSettings();
  return (
    <div className="grid gap-3">
      <p className="text-sm text-muted-foreground">{t("society.office.guide.settings_intro")}</p>
      <div className="divide-y divide-border rounded-lg border border-border">
        <SettingRow title={t("society.office.guide.set_always_run")} hint={t("society.office.guide.set_always_run_hint")}>
          <Switch checked={settings.alwaysRun} aria-label={t("society.office.guide.set_always_run")}
            onCheckedChange={(alwaysRun) => settings.set({ alwaysRun })} />
        </SettingRow>
        <SettingRow title={t("society.office.guide.set_hints")} hint={t("society.office.guide.set_hints_hint")}>
          <Button type="button" size="sm" variant="outline" disabled={!settings.hintsSeen} onClick={() => settings.set({ hintsSeen: false })}>
            {t("society.office.guide.set_hints_action")}
          </Button>
        </SettingRow>
      </div>
      <div><Button type="button" size="sm" variant="ghost" onClick={settings.reset}>{t("society.office.guide.set_reset")}</Button></div>
    </div>
  );
}

export function ReceptionPanel({ floor, layout, agents, actions }: {
  floor: OfficeFloor; layout: OfficeLayout; agents: readonly SocietyAgent[]; actions: OfficeActions;
}) {
  const t = useT();
  const tab = useReceptionTab((s) => s.tab);
  const setTab = useReceptionTab((s) => s.setTab);
  return (
    <Tabs value={tab} onValueChange={(value) => setTab(value as ReceptionTab)}>
      <TabsList aria-label={t("society.office.guide.tablist")}>
        {TABS.map((id) => <TabsTrigger key={id} value={id}>{t(`society.office.guide.tab_${id}`)}</TabsTrigger>)}
      </TabsList>
      <TabsContent value="agents"><AgentsTab agents={agents} actions={actions} /></TabsContent>
      <TabsContent value="places"><PlacesList layout={layout} /></TabsContent>
      <TabsContent value="controls"><ControlsTab floor={floor} /></TabsContent>
      <TabsContent value="settings"><SettingsTab /></TabsContent>
    </Tabs>
  );
}
