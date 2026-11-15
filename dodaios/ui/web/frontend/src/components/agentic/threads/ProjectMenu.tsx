import { useEffect, useState, type RefObject } from "react";
import { Copy, Folder, FolderOpen, Globe, Loader2, Pencil, Pin, PinOff, SquareCode, SquarePen, Trash2 } from "lucide-react";
import type { AgentChatSession } from "@/lib/agentChatApi";
import type { IdeProject } from "@/lib/agenticIdeApi";
import type { ProjectLaunchers } from "@/lib/chatLibraryApi";
import { cn } from "@/lib/utils";
import { fill, useT } from "@/i18n";
import { EDITOR_LOGOS, FILE_MANAGER_LABEL, MONO_EDITOR_LOGOS, cachedLaunchers, loadLaunchers } from "../projectLaunchers";
import { ThreadMenuItem, ThreadMenuSeparator, ThreadPopover } from "./ThreadPopover";
import { TeamThreadIcon } from "./ThreadStartIcons";

/** What the sidebar does for each row of a project's menu. */
export interface ProjectMenuActions {
  newThread: (project: IdeProject) => void;
  newTeam: (project: IdeProject) => void;
  openIn: (project: IdeProject, target: string, label: string) => void | Promise<void>;
  reveal: (project: IdeProject) => void | Promise<void>;
  copyPath: (project: IdeProject) => void | Promise<void>;
  rename: (project: IdeProject) => void;
  togglePin: (project: IdeProject) => void;
  /** Resolves true once the project is gone from the list. */
  remove: (project: IdeProject) => Promise<boolean>;
}

/** An editor's own app icon in a menu row; a single-colour glyph takes the text ink. */
function EditorLogo({ id, dim }: { id: string; dim: boolean }) {
  const src = EDITOR_LOGOS[id];
  if (!src) return <SquareCode className="h-3.5 w-3.5" />;
  if (MONO_EDITOR_LOGOS.has(id)) {
    const mask = `url("${src}") center / contain no-repeat`;
    return <span aria-hidden data-logo={src} className="h-4 w-4 bg-foreground" style={{ WebkitMask: mask, mask }} />;
  }
  return <img src={src} alt="" aria-hidden draggable={false} className={cn("h-4 w-4 object-contain", dim && "grayscale")} />;
}

/**
 * A project's menu in the threads sidebar, opened by right-click on its row
 * or by its ⋯ button: start work in it, open its folder elsewhere, rename,
 * pin, and take it out of the sidebar (asked once more, inside the menu).
 */
export function ProjectMenu({ anchor, point, project, threads, busy, actions, onClose }: {
  anchor: RefObject<HTMLElement | null>;
  point: { x: number; y: number } | null;
  project: IdeProject | null;
  /** The project's threads in the list (archived ones left out). */
  threads: AgentChatSession[];
  busy: boolean;
  actions: ProjectMenuActions;
  onClose: () => void;
}) {
  const t = useT();
  const projectId = project?.id ?? null;
  const [launchers, setLaunchers] = useState<ProjectLaunchers | null>(() => (projectId ? cachedLaunchers(projectId) ?? null : null));
  const [confirming, setConfirming] = useState(false);
  const [removing, setRemoving] = useState(false);

  useEffect(() => {
    setConfirming(false);
    if (!projectId) return;
    setLaunchers(cachedLaunchers(projectId) ?? null);
    let live = true;
    void loadLaunchers(projectId).then((found) => { if (live) setLaunchers(found); });
    return () => { live = false; };
  }, [projectId]);

  const close = () => { if (!removing) { setConfirming(false); onClose(); } };
  const run = (action: () => void) => () => { onClose(); action(); };

  if (!project) return null;
  const working = threads.filter((thread) => thread.running).length;
  const openSpaces = project.workspaces.filter((workspace) => workspace.status === "open");
  const agents = openSpaces.reduce((total, workspace) => total + workspace.terminals, 0);

  return <ThreadPopover anchor={anchor} point={point} open onClose={close} width={264}
    label={fill(t("ide_projects.project_actions_for"), { target: project.name })}>
    <div data-testid="thread-project-menu">
      {/* Which project this is about: its name and the folder it stands for. */}
      <div className="flex items-start gap-2 px-2 pb-1.5 pt-1.5">
        <Folder aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={1.75} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-foreground">{project.name}</div>
          <div title={project.path} className="truncate text-xs text-muted-foreground" style={{ direction: "rtl", textAlign: "left" }}>
            <bdi>{project.path}</bdi>
          </div>
        </div>
      </div>
      <ThreadMenuSeparator />
      {confirming
        ? <div className="p-2" data-testid="thread-project-confirm-remove">
          <p className="text-sm text-foreground">{fill(t("ide_threads.remove_project_title"), { project: project.name })}</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {fill(t(threads.length === 0 ? "ide_threads.remove_project_body_none" : threads.length === 1 ? "ide_threads.remove_project_body_one" : "ide_threads.remove_project_body_other"), { count: threads.length })}
            {agents > 0 && <> {fill(t("ide_threads.remove_project_stops"), {
              agents: fill(t(agents === 1 ? "ide_projects.running_agents_one" : "ide_projects.running_agents_other"), { count: agents }),
              workspaces: fill(t(openSpaces.length === 1 ? "ide_projects.open_workspaces_one" : "ide_projects.open_workspaces_other"), { count: openSpaces.length }),
            })}</>}
          </p>
          <div className="mt-3 flex justify-end gap-2">
            <button type="button" autoFocus disabled={removing} onClick={() => setConfirming(false)}
              className="rounded-md px-2.5 py-1 text-sm text-muted-foreground hover:bg-secondary disabled:opacity-50">{t("common.cancel")}</button>
            <button type="button" disabled={removing} data-testid="thread-project-confirm-remove-yes"
              onClick={() => {
                setRemoving(true);
                void actions.remove(project).then((gone) => {
                  setRemoving(false);
                  if (gone) { setConfirming(false); onClose(); }
                });
              }}
              className="flex items-center gap-1.5 rounded-md bg-destructive px-2.5 py-1 text-sm text-destructive-foreground disabled:opacity-60">
              {removing && <Loader2 aria-hidden className="h-3.5 w-3.5 animate-spin" />}
              {t(removing ? "ide_projects.removing" : "ide_threads.remove")}
            </button>
          </div>
        </div>
        : <div role="menu" aria-label={fill(t("ide_projects.project_actions_for"), { target: project.name })}>
          <ThreadMenuItem icon={<SquarePen className="h-3.5 w-3.5" strokeWidth={1.75} />} label={t("ide_threads.new_thread")}
            onSelect={run(() => actions.newThread(project))} />
          <ThreadMenuItem icon={<TeamThreadIcon className="h-3.5 w-3.5" />} label={t("team_threads.new")}
            onSelect={run(() => actions.newTeam(project))} />
          <ThreadMenuSeparator />
          {launchers?.editors.map((editor) => {
            const installed = editor.installed !== false;
            return <ThreadMenuItem key={editor.id} icon={<EditorLogo id={editor.id} dim={!installed} />}
              label={fill(t("ide_projects.open_in"), { editor: editor.label })}
              hint={installed ? undefined : t("ide_projects.not_installed")} disabled={!installed}
              onSelect={run(() => void actions.openIn(project, editor.id, editor.label))} />;
          })}
          {launchers?.file_manager && <ThreadMenuItem icon={<FolderOpen className="h-3.5 w-3.5" strokeWidth={1.75} />} label={t(FILE_MANAGER_LABEL)}
            onSelect={run(() => void actions.reveal(project))} />}
          {launchers?.remote_url && <ThreadMenuItem icon={<Globe className="h-3.5 w-3.5" strokeWidth={1.75} />}
            label={fill(t("ide_projects.open_on"), { target: launchers.remote_label ?? t("ide_projects.the_web") })}
            onSelect={run(() => void actions.openIn(project, "remote", launchers.remote_label ?? t("ide_projects.the_web_page")))} />}
          <ThreadMenuItem icon={<Copy className="h-3.5 w-3.5" strokeWidth={1.75} />} label={t("ide_projects.copy_path")}
            onSelect={run(() => void actions.copyPath(project))} />
          <ThreadMenuSeparator />
          <ThreadMenuItem icon={<Pencil className="h-3.5 w-3.5" strokeWidth={1.75} />} label={t("ide_projects.rename_project")} disabled={busy}
            onSelect={run(() => actions.rename(project))} />
          <ThreadMenuItem icon={project.pinned ? <PinOff className="h-3.5 w-3.5" strokeWidth={1.75} /> : <Pin className="h-3.5 w-3.5" strokeWidth={1.75} />}
            label={t(project.pinned ? "ide_projects.unpin_project" : "ide_projects.pin_project")} disabled={busy}
            onSelect={run(() => actions.togglePin(project))} />
          <ThreadMenuSeparator />
          {/* A project with a thread at work stays: removed, nobody would see it finish or ask. */}
          <ThreadMenuItem icon={<Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />} label={t("ide_threads.remove_project")} danger
            disabled={busy || working > 0}
            hint={working > 0 ? fill(t("ide_threads.count_working"), { count: working }) : undefined}
            onSelect={() => setConfirming(true)} />
        </div>}
    </div>
  </ThreadPopover>;
}
