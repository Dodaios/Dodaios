/**
 * Engineering's master systems console: start coding agents from the ship.
 * The IDE's own contract (a pane opens through POST /terminals; a first task
 * waits for the pane to come up and goes through its prompt endpoint), so a
 * pane started here is the same as one started in the grid, and walks in as
 * a technician to a free terminal.
 *
 * One batch runs at a time across every launcher, and closing the panel
 * stops its batch: no further pane is opened or briefed after that.
 */
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import {
  fetchIdeAgents, fetchIdeState, fetchWorkspacePanes, openTerminal, promptTerminal, startTerminal, type AgentStatus, type WorkspaceCard,
} from "@/lib/agenticIdeApi";
import { useWorkspacePanesStore } from "@/store/workspacePanes";
import { fill } from "@/i18n";
import { BrandedSelect } from "@/components/ui/select";
import { VerseDialog } from "./VerseDialog";

const MAX_LAUNCH = 4;
const COUNT_OPTIONS = Array.from({ length: MAX_LAUNCH }, (_, i) => ({ value: String(i + 1), label: String(i + 1) }));
const START_TIMEOUT_MS = 30_000;
const START_POLL_MS = 600;

/** A launch in progress; `cancelled` once its panel closed. */
interface Batch { cancelled: boolean }

let running: Batch | null = null;
const watchers = new Set<() => void>();

function setRunning(next: Batch | null): void {
  running = next;
  for (const watch of watchers) watch();
}

function watchRunning(watch: () => void): () => void {
  watchers.add(watch);
  return () => { watchers.delete(watch); };
}

/** True while any launcher's batch runs, a cancelled one included until its last request returns. */
function useBatchRunning(): boolean {
  return useSyncExternalStore(watchRunning, () => running !== null);
}

async function waitLive(workspaceId: string, name: string, batch: Batch): Promise<boolean> {
  const deadline = Date.now() + START_TIMEOUT_MS;
  while (Date.now() < deadline && !batch.cancelled) {
    try {
      const { panes } = await fetchWorkspacePanes();
      const row = panes.find((p) => p.workspace_id === workspaceId && p.name === name);
      if (row?.status === "live") return true;
      if (row && row.status !== "pending") return false;
    } catch (error) {
      console.warn("Verse launcher: pane poll failed", error);
    }
    await new Promise((r) => setTimeout(r, START_POLL_MS + Math.random() * 300));
  }
  return false;
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

interface Props {
  t: (key: string) => string;
  onClose: () => void;
  onOpenIde: () => void;
  say: (text: string) => void;
}

export function LauncherPanel({ t, onClose, onOpenIde, say }: Props) {
  const [workspaces, setWorkspaces] = useState<WorkspaceCard[] | null>(null);
  const [clis, setClis] = useState<AgentStatus[] | null>(null);
  const [workspaceId, setWorkspaceId] = useState("");
  const [cli, setCli] = useState("");
  const [count, setCount] = useState(1);
  const [task, setTask] = useState("");
  const [line, setLine] = useState<string | null>(null);
  const busy = useBatchRunning();
  const alive = useRef(true);
  const mine = useRef<Batch | null>(null);
  const first = useRef<HTMLDivElement>(null);

  useEffect(() => {
    alive.current = true;
    Promise.all([fetchIdeState(), fetchIdeAgents(true)]).then(([ide, list]) => {
      if (!alive.current) return;
      setWorkspaces(ide.workspaces);
      setWorkspaceId(ide.active_id || ide.workspaces[0]?.id || "");
      const usable = list.agents.filter((a) => a.installed && (a.kind ?? "cli") !== "shell");
      setClis(usable);
      setCli(usable[0]?.name ?? "");
    }, (error: unknown) => { if (alive.current) setLine(fill(t("verse.launcher.failed"), { reason: message(error) })); });
    return () => { alive.current = false; };
  }, [t]);
  useEffect(() => { first.current?.querySelector<HTMLElement>("button")?.focus(); }, [workspaces]);
  // Closing the panel stops the batch it started.
  useEffect(() => () => { if (mine.current) mine.current.cancelled = true; }, []);

  const launch = async () => {
    if (!cli || !workspaceId || running) return;
    const batch: Batch = { cancelled: false };
    mine.current = batch;
    setRunning(batch);
    const brief = task.trim();
    setLine(fill(t("verse.launcher.starting"), { count }));
    let opened = 0;
    try {
      for (let i = 0; i < count && !batch.cancelled; i++) {
        const { name } = await openTerminal({ workspace_id: workspaceId, agent: cli });
        opened++;
        void useWorkspacePanesStore.getState().load();
        if (!brief || batch.cancelled) continue;
        // A pane starts when a viewer attaches, and nobody views it from here.
        await startTerminal(name, workspaceId).catch((error: unknown) => console.warn("Verse launcher: start failed", error));
        if (await waitLive(workspaceId, name, batch) && !batch.cancelled) await promptTerminal(name, brief, { workspaceId });
      }
      void useWorkspacePanesStore.getState().load();
      if (opened > 0) say(fill(t("verse.launcher.started"), { count: opened }));
      if (!batch.cancelled) onClose();
    } catch (error) {
      if (batch.cancelled) console.warn("Verse launcher: stopped batch failed", error);
      else setLine(fill(t("verse.launcher.failed"), { reason: message(error) }));
    } finally {
      if (mine.current === batch) mine.current = null;
      if (running === batch) setRunning(null);
    }
  };

  const empty = clis !== null && clis.length === 0;
  const noWorkspace = workspaces !== null && workspaces.length === 0;
  return (
    <VerseDialog title={t("verse.launcher.title")} closeLabel={t("verse.card.close")} onClose={onClose} className="verse-form">
      <div className="verse-form-body">
        {empty || noWorkspace ? (
          <p className="verse-form-note">{noWorkspace ? t("verse.launcher.no_workspace") : t("verse.launcher.none")}</p>
        ) : (
          <>
            <div className="verse-field" ref={first}>
              <span className="verse-label">{t("verse.launcher.workspace")}</span>
              <BrandedSelect
                className="verse-input"
                ariaLabel={t("verse.launcher.workspace")}
                value={workspaceId}
                onValueChange={setWorkspaceId}
                disabled={!workspaces}
                options={(workspaces ?? []).map((w) => ({ value: w.id, label: w.name || w.id }))}
              />
            </div>
            <div className="verse-field-row">
              <div className="verse-field">
                <span className="verse-label">{t("verse.launcher.cli")}</span>
                <BrandedSelect
                  className="verse-input"
                  ariaLabel={t("verse.launcher.cli")}
                  value={cli}
                  onValueChange={setCli}
                  disabled={!clis}
                  options={(clis ?? []).map((c) => ({ value: c.name, label: c.display_name || c.name }))}
                />
              </div>
              <div className="verse-field verse-field-narrow">
                <span className="verse-label">{t("verse.launcher.count")}</span>
                <BrandedSelect
                  className="verse-input verse-num"
                  ariaLabel={t("verse.launcher.count")}
                  value={String(count)}
                  onValueChange={(value) => setCount(Number(value))}
                  options={COUNT_OPTIONS}
                />
              </div>
            </div>
            <label className="verse-field">
              <span className="verse-label">{t("verse.launcher.task")}</span>
              <textarea className="verse-input" rows={3} value={task} onChange={(e) => setTask(e.target.value)} />
            </label>
          </>
        )}
        {line && <p className="verse-form-note" role="status">{line}</p>}
      </div>
      <footer className="verse-form-foot">
        <button type="button" className="verse-btn" onClick={onOpenIde}>{t("verse.launcher.open_ide")}</button>
        {!empty && !noWorkspace && (
          <button type="button" className="verse-btn" data-primary="true" disabled={busy || !cli || !workspaceId} onClick={() => void launch()}>
            {t("verse.launcher.start")}
          </button>
        )}
      </footer>
    </VerseDialog>
  );
}
