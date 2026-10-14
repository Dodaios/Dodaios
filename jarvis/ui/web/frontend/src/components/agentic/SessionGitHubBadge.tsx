import { useEffect, useId, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { fill, useT } from "@/i18n";
import { openExternalUrl } from "@/lib/openExternal";
import { GitHubIcon, type GitHubIconName } from "./GitHubIcon";
import { PANE_BRAND, PANE_CHROME, themeFor, type TerminalAppearance } from "./terminalThemes";
import { FRESH_MS, useSessionGitHubPane, type SessionGitHubStatus } from "./useSessionGitHub";

const PR: Record<SessionGitHubStatus["state"], [GitHubIconName, string]> = {
  branch: ["git-branch", "ide_panes.github.state_branch"],
  draft: ["git-pull-request-draft", "ide_panes.github.state_draft"],
  open: ["git-pull-request", "ide_panes.github.state_open"],
  queued: ["git-merge-queue", "ide_panes.github.state_queued"],
  merged: ["git-merge", "ide_panes.github.state_merged"],
  closed: ["git-pull-request-closed", "ide_panes.github.state_closed"],
};

// Wide enough for a full `agent/topic` branch name beside its state.
const MENU_WIDTH = 460;

/** One branch as the header words it: where it leads, and what state it is in. */
interface BranchRow {
  branch: string;
  identity: string;
  icon: GitHubIconName;
  label: string;
  /** Null while nothing is on GitHub to open. */
  url: string | null;
  destination: string;
  /** The pull request number, when the link leads to one. */
  pullRequest: string | null;
  /** Merged or closed: listed, but no longer the pane's open work. */
  settled: boolean;
}

function describe(status: SessionGitHubStatus, t: (key: string) => string, pending = false): BranchRow | null {
  if (!status?.owned) return null;
  if (!/^[A-Za-z0-9][A-Za-z0-9-]*\/[A-Za-z0-9._-]+$/.test(status.repo) || !status.branch) return null;
  const identity = `${status.repo} · ${status.branch}`;
  // An old answer that a newer one is being read for keeps its state and
  // spins; it turns "unavailable" only when nothing newer is on its way.
  const unavailable = !status.available || (!pending && Date.now() - status.fetched_at * 1000 > FRESH_MS);
  if (!status.published) {
    // Nothing on GitHub to open yet: the pane still says which branch its work is on.
    return {
      branch: status.branch, identity, icon: "git-branch", url: null, destination: "", pullRequest: null, settled: false,
      label: t(unavailable ? "ide_panes.github.unavailable" : "ide_panes.github.local_only"),
    };
  }
  // The PR may belong to an upstream repository when this branch is a fork.
  const pullRequest = /^https:\/\/github\.com\/[A-Za-z0-9][A-Za-z0-9-]*\/[A-Za-z0-9._-]+\/pull\/([1-9]\d*)$/.exec(status.url);
  const url = pullRequest ? status.url : `https://github.com/${status.repo}/tree/${encodeURIComponent(status.branch)}`;
  const destination = pullRequest
    ? fill(t("ide_panes.github.dest_pr"), { number: pullRequest[1] })
    : t("ide_panes.github.dest_branch");
  const [icon, labelKey] = unavailable
    ? ["git-branch" as const, "ide_panes.github.unavailable"]
    : PR[status.state] ?? ["git-branch" as const, "ide_panes.github.branch_generic"];
  return {
    branch: status.branch, identity, icon, label: t(labelKey), url, destination,
    pullRequest: pullRequest ? pullRequest[1] : null,
    settled: !unavailable && (status.state === "merged" || status.state === "closed"),
  };
}

/**
 * The spinner a check that is still running wears: a quiet track and a turning
 * arc in the pending hue, drawn round the symbol without taking room of its own.
 */
function PendingRing({ appearance }: { appearance: TerminalAppearance }) {
  return <span aria-hidden="true" data-testid="session-github-pending"
    className="pointer-events-none absolute -inset-0.5" style={{ color: themeFor(appearance).yellow }}>
    <svg viewBox="0 0 20 20" className="block h-full w-full animate-spin motion-reduce:animate-none">
      <circle cx="10" cy="10" r="8.5" fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="1.5" />
      <path d="M10 1.5a8.5 8.5 0 0 1 8.5 8.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  </span>;
}

/** The header's symbol; while its status is being confirmed it sits inside the spinner. */
function Glyph({ icon, pending, appearance }: {
  icon: GitHubIconName | null;
  pending: boolean;
  appearance: TerminalAppearance;
}) {
  const size = pending ? 10 : 16;
  return <span className="relative inline-flex h-4 w-4 shrink-0 items-center justify-center">
    {icon && <GitHubIcon name={icon} width={size} height={size} className="block shrink-0" />}
    {pending && <PendingRing appearance={appearance} />}
  </span>;
}

/** A session that worked on several branches: one symbol, the rest one click away. */
function BranchList({ rows, appearance, pending }: {
  rows: BranchRow[];
  appearance: TerminalAppearance;
  pending: boolean;
}) {
  const t = useT();
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const open = position !== null;
  const brand = PANE_BRAND[appearance];
  const chrome = PANE_CHROME[appearance];
  const shown = rows[0];

  useEffect(() => {
    if (!open) return;
    const away = (event: PointerEvent) => {
      if (event.target instanceof Node && !menuRef.current?.contains(event.target)
        && !buttonRef.current?.contains(event.target)) setPosition(null);
    };
    const dismiss = () => setPosition(null);
    document.addEventListener("pointerdown", away, true);
    window.addEventListener("resize", dismiss);
    window.addEventListener("blur", dismiss);
    return () => {
      document.removeEventListener("pointerdown", away, true);
      window.removeEventListener("resize", dismiss);
      window.removeEventListener("blur", dismiss);
    };
  }, [open]);

  const toggle = () => {
    const rect = buttonRef.current?.getBoundingClientRect();
    if (!rect) return;
    const left = Math.max(8, Math.min(rect.right - MENU_WIDTH, window.innerWidth - MENU_WIDTH - 8));
    setPosition((current) => current ? null : { left, top: rect.bottom + 4 });
  };
  const close = () => { setPosition(null); buttonRef.current?.focus(); };

  const menu = createPortal(<div ref={menuRef} id={menuId} role="menu" hidden={!open}
    data-testid="session-github-branches" aria-label={t("ide_panes.github.branches_title")}
    className="fixed z-[90] max-w-[calc(100vw-16px)] rounded-lg border p-1 shadow-lg"
    style={{ ...(position ?? { left: 0, top: 0 }), width: MENU_WIDTH, borderColor: chrome.border,
      background: chrome.float, color: brand.ink, "--pane-chip": brand.chip } as CSSProperties}
    onPointerDown={(event) => event.stopPropagation()}
    onMouseDown={(event) => event.stopPropagation()}
    onKeyDown={(event) => {
      if (event.key === "Escape" || event.key === "Tab") { event.preventDefault(); event.stopPropagation(); close(); return; }
      if (!["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const items = Array.from(menuRef.current?.querySelectorAll<HTMLElement>("a[role=menuitem]") ?? []);
      const at = items.indexOf(document.activeElement as HTMLElement);
      const index = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1
        : (at + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      items[index]?.focus();
    }}>
    <div className="px-2.5 pb-1 pt-1.5 text-[11px]" style={{ color: brand.inkFaint }}>{t("ide_panes.github.branches_title")}</div>
    {rows.map((row) => {
      const line = <>
        <GitHubIcon name={row.icon} width={16} height={16} className="block shrink-0" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate font-mono text-xs">{row.branch}</span>
        <span className="shrink-0 text-[11px]" style={{ color: brand.inkFaint }}>
          {row.pullRequest ? `#${row.pullRequest} · ` : ""}{row.label}
        </span>
      </>;
      const layout = `flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-left ${row.settled ? "opacity-60" : ""}`;
      if (!row.url) {
        return <div key={row.identity} role="menuitem" aria-disabled="true" title={`${row.identity}\n${row.label}`}
          className={layout}>{line}</div>;
      }
      const url = row.url;
      return <a key={row.identity} role="menuitem" href={url} target="_blank" rel="noopener noreferrer"
        aria-label={fill(t("ide_panes.github.open_aria"), { destination: row.destination, identity: row.identity })}
        title={`${row.identity}\n${row.label}\n${fill(t("ide_panes.github.open_title"), { destination: row.destination })}`}
        className={`${layout} hover:bg-[color:var(--pane-chip)] hover:opacity-100 focus:bg-[color:var(--pane-chip)] focus:opacity-100 focus:outline-none`}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setPosition(null);
          // WebView2 drops target=_blank: use the desktop's real-browser bridge.
          void openExternalUrl(url);
        }}>{line}</a>;
    })}
  </div>, document.body);

  return <>
    <button ref={buttonRef} type="button" data-header-control="true" data-testid="session-github-status"
      aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined}
      aria-label={fill(t("ide_panes.github.branches_aria"), { count: rows.length, identity: shown.identity })}
      title={`${shown.identity}\n${shown.label}\n${t("ide_panes.github.branches_title")}: ${rows.length}${pending ? `\n${t("ide_panes.github.refreshing")}` : ""}`}
      className={`inline-flex h-6 shrink-0 items-center justify-center gap-0.5 rounded px-1 transition-opacity hover:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-current ${shown.url ? "opacity-75" : "opacity-50"}`}
      style={{ color: brand.inkMuted }}
      onPointerDown={(event) => event.stopPropagation()}
      onKeyDown={(event) => { if (event.key === "ArrowDown" && !open) { event.preventDefault(); toggle(); } }}
      onClick={(event) => { event.stopPropagation(); toggle(); }}>
      <Glyph icon={shown.icon} pending={pending} appearance={appearance} />
      <span className="text-[10px] leading-none tabular-nums" aria-hidden="true">{rows.length}</span>
    </button>
    {menu}
  </>;
}

export function GitHubStatusBadge({ status, appearance, pending = false }: {
  status: SessionGitHubStatus | null;
  appearance: TerminalAppearance;
  /** The status is still being read, or confirmed after it went old: it spins meanwhile. */
  pending?: boolean;
}) {
  const t = useT();
  const shown = status ? describe(status, t, pending) : null;
  if (!shown) {
    if (!pending) return null;
    // Nothing known yet: the spinner holds the place the branch will take.
    const label = t(status === null ? "ide_panes.github.loading" : "ide_panes.github.refreshing");
    return <span data-header-control="true" data-testid="session-github-status" data-state="loading"
      role="status" aria-label={label} title={label}
      className="inline-flex h-6 w-6 shrink-0 items-center justify-center"
      style={{ color: PANE_BRAND[appearance].inkMuted }}>
      <Glyph icon={null} pending appearance={appearance} />
    </span>;
  }
  const others = (status?.others ?? []).map((other) => describe(other, t, pending))
    .filter((row): row is BranchRow => row !== null && row.identity !== shown.identity);
  if (others.length) return <BranchList rows={[shown, ...others]} appearance={appearance} pending={pending} />;
  const note = pending ? `\n${t("ide_panes.github.refreshing")}` : "";
  if (!shown.url) {
    return <span data-header-control="true" data-testid="session-github-status" role="img"
      aria-label={`${shown.identity}: ${shown.label}`} title={`${shown.identity}\n${shown.label}${note}`}
      className={`inline-flex h-6 w-6 shrink-0 items-center justify-center ${pending ? "opacity-75" : "opacity-50"}`}
      style={{ color: PANE_BRAND[appearance].inkMuted }}>
      <Glyph icon="git-branch" pending={pending} appearance={appearance} />
    </span>;
  }
  const url = shown.url;
  return <a data-header-control="true" data-testid="session-github-status"
    href={url} target="_blank" rel="noopener noreferrer"
    aria-label={fill(t("ide_panes.github.open_aria"), { destination: shown.destination, identity: shown.identity })}
    title={`${shown.identity}\n${shown.label}\n${fill(t("ide_panes.github.open_title"), { destination: shown.destination })}${note}`}
    className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded opacity-75 transition-opacity hover:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-current"
    style={{ color: PANE_BRAND[appearance].inkMuted }}
    onPointerDown={(event) => event.stopPropagation()}
    onClick={(event) => {
      event.preventDefault();
      event.stopPropagation();
      // WebView2 drops target=_blank: use the desktop's real-browser bridge.
      void openExternalUrl(url);
    }}>
    <Glyph icon={shown.icon} pending={pending} appearance={appearance} />
  </a>;
}

export function SessionGitHubBadge({ workspaceId, name, appearance }: {
  workspaceId?: string;
  name: string;
  appearance: TerminalAppearance;
}) {
  const { status, pending } = useSessionGitHubPane(workspaceId, name);
  return <GitHubStatusBadge status={status} pending={pending} appearance={appearance} />;
}
