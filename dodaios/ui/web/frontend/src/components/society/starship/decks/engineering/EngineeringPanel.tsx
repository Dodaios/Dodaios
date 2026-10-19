/**
 * The master systems display's panel: start new coding agents from the ship.
 *
 * The same contract Mission Control used on the old coding floor, nothing of
 * its own: panes open through the IDE's `POST /terminals` (workspace, CLI, how
 * many), and a first task waits for each pane to come up, then goes through
 * `/terminals/{name}/prompt`, the path voice and the grid use. A new pane
 * appears on the deck at a free console of its workspace's bay.
 */
import { BrandedSelect } from "@/components/ui/select";
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Minus, Plus, X } from "lucide-react";
import {
  fetchIdeAgents, fetchIdeState, fetchWorkspacePanes, openTerminal, promptTerminal, startTerminal,
  type AgentStatus, type WorkspaceCard,
} from "@/lib/agenticIdeApi";
import { useWorkspacePanesStore } from "@/store/workspacePanes";
import { AgentMark } from "@/components/agentic/AgentMark";
import type { DeckPanelProps } from "../registry";
import "./engineering.css";

/** At most this many agents per launch. */
const MAX_LAUNCH = 4;
const START_TIMEOUT_MS = 30_000;
const START_POLL_MS = 600;
const START_JITTER_MS = 300;

type LaunchLine = { tone: "busy" | "ok" | "warn" | "error"; text: string };

/** Coding CLIs a new agent can run: installed, and not a plain shell. Pure. */
function launchableClis(agents: readonly AgentStatus[]): AgentStatus[] {
  return agents.filter((a) => a.installed && (a.kind ?? "cli") !== "shell");
}

/** Wait until pane `name` of `workspaceId` is live; false when it failed or the clock ran out. */
async function waitLive(workspaceId: string, name: string): Promise<boolean> {
  const deadline = Date.now() + START_TIMEOUT_MS;
  for (;;) {
    try {
      const { panes } = await fetchWorkspacePanes();
      const row = panes.find((p) => p.workspace_id === workspaceId && p.name === name);
      if (row?.status === "live") return true;
      if (row && row.status !== "pending") return false;
    } catch (err) {
      // One failed poll is not an answer; the next one decides.
      console.warn("Engineering launcher: pane poll failed", err);
    }
    if (Date.now() >= deadline) return false;
    await new Promise((resolve) => setTimeout(resolve, START_POLL_MS + Math.random() * START_JITTER_MS));
  }
}

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

const FOCUSABLE = "button:not([disabled]), select:not([disabled]), textarea:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex='-1'])";

export function EngineeringPanel({ actions, panes }: DeckPanelProps) {
  const { t, closePanel, say, openSection } = actions;
  const dialog = useRef<HTMLElement>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceCard[] | null>(null);
  const [clis, setClis] = useState<AgentStatus[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [workspaceId, setWorkspaceId] = useState("");
  const [cli, setCli] = useState("");
  const [count, setCount] = useState(1);
  const [task, setTask] = useState("");
  const [running, setRunning] = useState(false);
  const [lines, setLines] = useState<LaunchLine[]>([]);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    Promise.all([fetchIdeState(), fetchIdeAgents(true)])
      .then(([state, list]) => {
        if (!alive.current) return;
        setWorkspaces(state.workspaces);
        setWorkspaceId((current) => current || state.active_id || state.workspaces[0]?.id || "");
        const usable = launchableClis(list.agents);
        setClis(usable);
        setCli((current) => current || usable[0]?.name || "");
      })
      .catch((err) => { if (alive.current) setLoadError(errorText(err)); });
    return () => { alive.current = false; };
  }, []);

  // Focus moves into the dialog and back to where it was on close.
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    dialog.current?.focus();
    return () => { if (before && document.contains(before)) before.focus(); };
  }, []);

  const counts = useMemo(() => {
    const c = { working: 0, waiting: 0, idle: 0 };
    for (const o of panes) c[o.dot === "working" ? "working" : o.dot === "idle" ? "idle" : "waiting"] += 1;
    return c;
  }, [panes]);

  const setLine = (index: number, line: LaunchLine) => {
    if (alive.current) setLines((prev) => { const next = [...prev]; next[index] = line; return next; });
  };
  const fill = (key: string, name: string) => t(key).replace("{pane}", name);

  /** Wait for one new pane, then hand it the task. */
  const settle = async (i: number, name: string, wsId: string, brief: string) => {
    if (!brief) { setLine(i, { tone: "ok", text: fill("ship.engineering.panel.done_open", name) }); return; }
    setLine(i, { tone: "busy", text: fill("ship.engineering.panel.waiting", name) });
    try {
      // A pane starts when a viewer first attaches, and nobody views it from here.
      await startTerminal(name, wsId);
    } catch (err) {
      console.warn("Engineering launcher: pane start request failed", err);
    }
    if (!(await waitLive(wsId, name))) { setLine(i, { tone: "warn", text: fill("ship.engineering.panel.not_started", name) }); return; }
    setLine(i, { tone: "busy", text: fill("ship.engineering.panel.briefing", name) });
    try {
      const result = await promptTerminal(name, brief, { workspaceId: wsId });
      setLine(i, result.submitted === true
        ? { tone: "ok", text: fill("ship.engineering.panel.done_briefed", name) }
        : { tone: "warn", text: result.detail || t("ship.engineering.panel.unconfirmed") });
    } catch (err) {
      setLine(i, { tone: "error", text: errorText(err) });
    }
  };

  const ready = Boolean(cli) && Boolean(workspaceId) && !running;

  const launch = async () => {
    if (!ready) return;
    setRunning(true);
    setLines([]);
    const brief = task.trim();
    let opened = 0;
    for (let i = 0; i < count; i += 1) {
      setLine(i, { tone: "busy", text: t("ship.engineering.panel.opening") });
      let name = "";
      try {
        name = (await openTerminal({ workspace_id: workspaceId, agent: cli })).name;
      } catch (err) {
        setLine(i, { tone: "error", text: t("ship.engineering.panel.failed").replace("{error}", errorText(err)) });
        break;
      }
      opened += 1;
      void useWorkspacePanesStore.getState().load();
      await settle(i, name, workspaceId, brief);
    }
    void useWorkspacePanesStore.getState().load();
    if (opened > 0) {
      say(t("ship.engineering.panel.launched").replace("{count}", String(opened)));
      if (brief && alive.current) setTask("");
    }
    if (alive.current) setRunning(false);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closePanel(); return; }
    if (e.key !== "Tab" || !dialog.current) return;
    // Keep Tab inside the dialog.
    const items = [...dialog.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    if (items.length === 0) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };

  const openIde = useCallback(() => { closePanel(); openSection("agentic-ide"); }, [closePanel, openSection]);

  return (
    <div className="ship-scrim" onClick={closePanel}>
      <section ref={dialog} className="ship-panel eng-launch" role="dialog" aria-modal="true" aria-labelledby="eng-launch-title"
        tabIndex={-1} onClick={(e) => e.stopPropagation()} onKeyDown={onKeyDown}>
        <header className="eng-launch-head">
          <div>
            <div className="ship-eyebrow">{t("ship.station.systems.name")}</div>
            <h2 id="eng-launch-title">{t("ship.engineering.panel.title")}</h2>
          </div>
          <button type="button" className="ship-tool" aria-label={t("ship.close")} onClick={closePanel}><X size={16} aria-hidden /></button>
        </header>
        <p className="eng-launch-crew">
          <span><i className="ship-dot" data-state="working" />{t("ship.crew.working").replace("{count}", String(counts.working))}</span>
          <span><i className="ship-dot" data-state="waiting" />{t("ship.crew.waiting").replace("{count}", String(counts.waiting))}</span>
          <span><i className="ship-dot" data-state="idle" />{t("ship.crew.idle").replace("{count}", String(counts.idle))}</span>
        </p>

        {loadError ? <p className="eng-launch-note" role="alert">{t("ship.engineering.panel.load_failed").replace("{error}", loadError)}</p>
          : !workspaces || !clis ? <p className="eng-launch-note" role="status">{t("ship.engineering.panel.loading")}</p>
          : (
            <>
              <fieldset className="eng-launch-field">
                <legend className="ship-eyebrow">{t("ship.engineering.panel.cli")}</legend>
                {clis.length === 0 ? <p className="eng-launch-note">{t("ship.engineering.panel.no_clis")}</p> : (
                  <div className="eng-launch-clis" role="radiogroup" aria-label={t("ship.engineering.panel.cli")}>
                    {clis.map((a) => (
                      <button key={a.name} type="button" role="radio" aria-checked={cli === a.name} disabled={running}
                        title={a.description || a.display_name} onClick={() => setCli(a.name)}>
                        <AgentMark agent={a.name} label={a.display_name} logoUrl={a.logo_url || undefined} size="sm" />
                        <span>{a.display_name}</span>
                      </button>
                    ))}
                  </div>
                )}
              </fieldset>

              <label className="eng-launch-field">
                <span className="ship-eyebrow">{t("ship.engineering.panel.workspace")}</span>
                {workspaces.length === 0 ? (
                  <span className="eng-launch-note">
                    {t("ship.engineering.panel.no_workspace")}{" "}
                    <button type="button" className="eng-launch-link" onClick={openIde}>{t("ship.engineering.panel.open_ide")}</button>
                  </span>
                ) : (
                  <BrandedSelect className="eng-launch-input" value={workspaceId} disabled={running} onValueChange={setWorkspaceId}
                    ariaLabel={t("ship.engineering.panel.workspace")}
                    options={workspaces.map((w) => ({ value: w.id, label: w.name, hint: w.branch || undefined }))} />
                )}
              </label>

              <label className="eng-launch-field">
                <span className="ship-eyebrow">{t("ship.engineering.panel.task")}</span>
                <textarea className="eng-launch-input" rows={3} value={task} maxLength={8000} disabled={running}
                  placeholder={t("ship.engineering.panel.task_placeholder")}
                  onChange={(e) => setTask(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void launch(); } }} />
              </label>

              <div className="eng-launch-go">
                <div className="eng-launch-stepper" role="group" aria-label={t("ship.engineering.panel.count")}>
                  <button type="button" disabled={running || count <= 1} onClick={() => setCount((n) => n - 1)}
                    aria-label={t("ship.engineering.panel.fewer")}><Minus size={14} aria-hidden /></button>
                  <output aria-live="polite">{count}</output>
                  <button type="button" disabled={running || count >= MAX_LAUNCH} onClick={() => setCount((n) => n + 1)}
                    aria-label={t("ship.engineering.panel.more")}><Plus size={14} aria-hidden /></button>
                </div>
                <button type="button" className="ship-btn" data-primary="true" disabled={!ready} onClick={() => void launch()}>
                  {count === 1 ? t("ship.engineering.panel.start_one") : t("ship.engineering.panel.start_many").replace("{count}", String(count))}
                </button>
              </div>
              <p className="eng-launch-hint">{t("ship.engineering.panel.hint")}</p>
            </>
          )}

        {lines.length > 0 && (
          <ul className="eng-launch-log" aria-live="polite">
            {lines.map((line, i) => <li key={i} data-tone={line.tone}><i aria-hidden />{line.text}</li>)}
          </ul>
        )}
      </section>
    </div>
  );
}
