/**
 * "Built for you" — everything the self-building loop made on its own.
 *
 * The person is no longer asked about every build, so this page is the
 * counterweight: every build is on it with the one sentence it exists for,
 * where it stands, and the action that applies to it. The page is organised
 * by what each build asks of the person — waiting for a yes, on trial, being
 * built, kept, gone — not as a table of rows. A build opens into its case file
 * on the right (`BuildDetail`).
 *
 * It never interrupts: no toast, no sound, no voice. New builds show up here,
 * as a quiet count on the nav row, and in the one-line digest at the top.
 * Live through `SelfBuildChanged` (hooks/useWebSocket.ts). docs/self-build.md.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ChevronDown, Loader2, Pause, Play, Settings2, OctagonX } from "lucide-react";
import { fill, useLocaleChunk, useT } from "@/i18n";
import { useRunLocale } from "@/components/runs/format";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { useSettingsJump } from "@/store/settingsJump";
import { useSelfBuildFocus } from "@/store/selfBuildFocus";
import {
  useBuildAction,
  useSelfBuildDigest,
  useSelfBuildList,
  useSelfBuildPause,
  useSelfBuildSettings,
  useSetSocietyKillSwitch,
  useSocietyKillSwitch,
  type BuildAction,
} from "@/hooks/useSelfBuild";
import {
  SelfBuildApiError,
  reachedStep,
  shelfOf,
  trialProgress,
  type Build,
  type BuildDigest,
  type SelfBuildStatus,
  type Shelf,
} from "@/lib/selfBuildApi";
import { BuildActions } from "./selfBuild/BuildActions";
import { BuildDetail } from "./selfBuild/BuildDetail";
import { KindIcon, LifecycleRail, relativeTime } from "./selfBuild/shared";

const SHELVES: readonly Shelf[] = ["waiting", "trial", "working", "kept", "past"];

export function SelfBuildView() {
  const ready = useLocaleChunk("self_build");
  const t = useT();
  const list = useSelfBuildList();
  const digest = useSelfBuildDigest(24);
  const settings = useSelfBuildSettings();
  const act = useBuildAction();
  const [selectedId, setSelectedId] = useState<string | null>(() => useSelfBuildFocus.getState().take());
  const [error, setError] = useState<string | null>(null);
  const focusRequest = useSelfBuildFocus((s) => s.buildId);

  // A badge elsewhere asked for a build while this view was already open.
  useEffect(() => {
    if (focusRequest) setSelectedId(useSelfBuildFocus.getState().take());
  }, [focusRequest]);

  const builds = list.data?.builds ?? [];
  const status = list.data?.status;
  const selected = builds.find((b) => b.id === selectedId) ?? null;
  const limits = settings.data?.settings;
  // Accepting starts a build, so it waits while building is paused.
  const canBuild = (build: Build) => Boolean(status?.builders.includes(build.kind)) && !status?.paused;
  const blockedTitle = (build: Build) =>
    status?.paused ? t("self_build.notes.paused") : !status?.builders.includes(build.kind) ? t("self_build.no_builder") : undefined;

  const onAction = (build: Build, action: BuildAction) => {
    setError(null);
    act.mutate(
      { id: build.id, action },
      { onError: (err) => setError(fill(t("self_build.error.action"), { detail: err.message })) },
    );
  };

  if (!ready) return <Centered><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden /></Centered>;

  const unavailable = list.error instanceof SelfBuildApiError && list.error.status === 503;

  return (
    <div data-testid="self-build-view" className="flex h-full min-h-0 flex-col overflow-y-auto">
      <div className="mx-auto flex w-full max-w-[1240px] flex-1 flex-col px-6 pb-16 pt-10 sm:px-10">
        <Header status={status} />
        <Notes status={status} />
        <DigestLine digest={digest.data} />
        {error && (
          <p role="alert" className="mt-4 rounded-lg border border-destructive/40 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        )}

        {list.isPending ? (
          <Centered><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-label={t("self_build.loading")} /></Centered>
        ) : unavailable || list.error ? (
          <p role="alert" className="mt-10 text-base text-muted-foreground">{t("self_build.error.unavailable")}</p>
        ) : builds.length === 0 ? (
          <EmptyLoop />
        ) : (
          <div className="mt-8 grid min-h-0 flex-1 grid-cols-1 items-start gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(360px,440px)]">
            <div className="min-w-0 space-y-9" data-testid="self-build-shelves">
              {SHELVES.map((shelf) => (
                <ShelfSection
                  key={shelf}
                  shelf={shelf}
                  builds={builds.filter((b) => shelfOf(b) === shelf)}
                  selectedId={selectedId}
                  onSelect={(b) => setSelectedId(b.id === selectedId ? null : b.id)}
                  canBuild={canBuild}
                  blockedTitle={blockedTitle}
                  busyId={act.isPending ? act.variables?.id ?? null : null}
                  onAction={onAction}
                  limits={limits}
                />
              ))}
            </div>
            <aside className="min-w-0 lg:sticky lg:top-6 lg:max-h-[calc(100vh-7rem)] lg:min-h-[420px] lg:[&>article]:max-h-[calc(100vh-7rem)]">
              {selected ? (
                <BuildDetail
                  key={selected.id}
                  build={selected}
                  limits={limits}
                  canBuild={canBuild(selected)}
                  blockedTitle={blockedTitle(selected)}
                  busy={act.isPending && act.variables?.id === selected.id}
                  onAction={onAction}
                  onClose={() => setSelectedId(null)}
                />
              ) : (
                <PickHint />
              )}
            </aside>
          </div>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ header

function Header({ status }: { status: SelfBuildStatus | undefined }) {
  const t = useT();
  const pause = useSelfBuildPause();
  const setActive = useEventStore((s) => s.setActiveSection);
  const [confirmStop, setConfirmStop] = useState(false);
  const kill = useSocietyKillSwitch();
  const setKill = useSetSocietyKillSwitch();
  const paused = Boolean(status?.paused);
  const tone = !status ? "idle" : !status.enabled ? "off" : paused ? "paused" : status.silent ? "silent" : "running";

  const openSettings = () => {
    useSettingsJump.getState().request("self-build");
    setActive("settings");
  };

  return (
    <header className="flex flex-wrap items-end gap-x-6 gap-y-4">
      <div className="min-w-0 flex-1">
        <h1 className="font-display text-2xl font-semibold text-foreground-strong">{t("self_build.title")}</h1>
        <p className="mt-1 max-w-xl text-base text-muted-foreground">{t("self_build.subtitle")}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {status && (
          <span
            data-testid="self-build-status"
            data-tone={tone}
            className="mr-1 inline-flex items-center gap-2 text-sm text-muted-foreground"
          >
            <span
              aria-hidden
              className={cn(
                "h-2 w-2 rounded-full",
                tone === "running" && "bg-success",
                tone === "paused" && "bg-warning",
                tone === "silent" && "bg-info",
                tone === "off" && "bg-border-strong",
              )}
            />
            {t(`self_build.status.${tone === "idle" ? "running" : tone}`)}
          </span>
        )}
        {status?.enabled && (
          <button
            type="button"
            data-testid="self-build-pause"
            aria-pressed={paused}
            title={t("self_build.pause_hint")}
            disabled={pause.isPending}
            onClick={() => pause.mutate(!paused)}
            className={cn(
              "inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
              paused ? "bg-primary text-primary-foreground hover:bg-primary/90" : "border border-border-strong text-foreground hover:bg-secondary",
            )}
          >
            {paused ? <Play className="h-3.5 w-3.5" aria-hidden /> : <Pause className="h-3.5 w-3.5" aria-hidden />}
            {paused ? t("self_build.resume") : t("self_build.pause")}
          </button>
        )}
        <button
          type="button"
          onClick={openSettings}
          aria-label={t("self_build.settings")}
          title={t("self_build.settings")}
          data-testid="self-build-settings"
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Settings2 className="h-4 w-4" aria-hidden />
        </button>
        {kill.data !== true && (
          <button
            type="button"
            data-testid="society-stop-all"
            title={t("self_build.stop_all_hint")}
            onClick={() => setConfirmStop(true)}
            className="inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-sm text-destructive hover:bg-destructive/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <OctagonX className="h-4 w-4" aria-hidden />
            {t("self_build.stop_all")}
          </button>
        )}
      </div>
      {confirmStop && (
        <ConfirmStop
          busy={setKill.isPending}
          onCancel={() => setConfirmStop(false)}
          onConfirm={() => setKill.mutate(true, { onSettled: () => setConfirmStop(false) })}
        />
      )}
    </header>
  );
}

function Notes({ status }: { status: SelfBuildStatus | undefined }) {
  const t = useT();
  const kill = useSocietyKillSwitch();
  const setKill = useSetSocietyKillSwitch();
  const setActive = useEventStore((s) => s.setActiveSection);
  const notes: ReactNode[] = [];
  if (kill.data === true) {
    notes.push(
      <Note key="stopped" tone="destructive" testId="note-stopped"
        action={{ label: t("self_build.notes.release"), onClick: () => setKill.mutate(false), busy: setKill.isPending }}>
        {t("self_build.notes.stopped")}
      </Note>,
    );
  }
  if (status && !status.enabled) {
    notes.push(
      <Note key="off" tone="muted" testId="note-off"
        action={{
          label: t("self_build.notes.turn_on"),
          onClick: () => {
            useSettingsJump.getState().request("self-build");
            setActive("settings");
          },
        }}>
        {t("self_build.notes.off")}
      </Note>,
    );
  } else if (status?.paused) {
    notes.push(
      // The resume button sits in the header right above; the note only says why.
      <Note key="paused" tone="warning" testId="note-paused">
        {t("self_build.notes.paused")}
      </Note>,
    );
  } else if (status?.silent) {
    notes.push(<Note key="silent" tone="muted" testId="note-silent">{t("self_build.notes.silent")}</Note>);
  }
  if (!notes.length) return null;
  return <div className="mt-6 space-y-2">{notes}</div>;
}

function Note({
  tone,
  children,
  action,
  testId,
}: {
  tone: "muted" | "warning" | "destructive";
  children: ReactNode;
  action?: { label: string; onClick: () => void; busy?: boolean };
  testId: string;
}) {
  return (
    <div
      data-testid={testId}
      className={cn(
        "flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border px-4 py-2.5 text-sm",
        tone === "muted" && "border-border text-muted-foreground",
        tone === "warning" && "border-warning/40 text-foreground",
        tone === "destructive" && "border-destructive/40 text-foreground",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "h-1.5 w-1.5 shrink-0 rounded-full",
          tone === "muted" && "bg-border-strong",
          tone === "warning" && "bg-warning",
          tone === "destructive" && "bg-destructive",
        )}
      />
      <span className="min-w-0 flex-1">{children}</span>
      {action && (
        <button
          type="button"
          onClick={action.onClick}
          disabled={action.busy}
          className="shrink-0 rounded-md px-2 py-1 text-sm font-medium text-foreground underline-offset-4 hover:underline disabled:opacity-50"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ digest

/**
 * The daily glance as one sentence-like line, not a row of stat tiles: what
 * changed since yesterday, and how much is live now.
 */
function DigestLine({ digest }: { digest: BuildDigest | undefined }) {
  const t = useT();
  if (!digest) return null;
  const counts = digest.counts;
  const built = (counts.trial ?? 0) + (counts.building ?? 0) + (counts.proving ?? 0);
  const parts: [string, number][] = [
    ["built", built],
    ["proposed", counts.proposed ?? 0],
    ["kept", counts.kept ?? 0],
    ["archived", counts.archived ?? 0],
    ["undone", counts.undone ?? 0],
  ];
  const shown = parts.filter(([, n]) => n > 0);
  return (
    <p data-testid="self-build-digest" className="mt-6 flex flex-wrap items-baseline gap-x-3 gap-y-1 border-y border-border py-3 text-base">
      <span className="text-sm font-medium text-muted-foreground">{t("self_build.digest.label")}</span>
      {shown.length === 0 ? (
        <span className="text-muted-foreground">{t("self_build.digest.nothing")}</span>
      ) : (
        shown.map(([key, n], index) => (
          <span key={key} className="text-foreground">
            {index > 0 && <span aria-hidden className="mr-3 text-border-strong">·</span>}
            <Count text={fill(t(`self_build.digest.${key}`), { count: n })} n={n} />
          </span>
        ))
      )}
      <span className="ml-auto text-sm text-muted-foreground">
        <Count text={fill(t("self_build.digest.live"), { count: digest.live })} n={digest.live} />
      </span>
    </p>
  );
}

/** Puts the number of a "{count} built" string in strong ink, wherever the locale placed it. */
function Count({ text, n }: { text: string; n: number }) {
  const digits = String(n);
  const at = text.indexOf(digits);
  if (at < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <span className="font-semibold tabular-nums text-foreground-strong">{digits}</span>
      {text.slice(at + digits.length)}
    </>
  );
}

// ------------------------------------------------------------------ shelves

function ShelfSection({
  shelf,
  builds,
  selectedId,
  onSelect,
  canBuild,
  blockedTitle,
  busyId,
  onAction,
  limits,
}: {
  shelf: Shelf;
  builds: Build[];
  selectedId: string | null;
  onSelect: (build: Build) => void;
  canBuild: (build: Build) => boolean;
  blockedTitle: (build: Build) => string | undefined;
  busyId: string | null;
  onAction: (build: Build, action: BuildAction) => void;
  limits: { trial_days: number; trial_uses: number } | undefined;
}) {
  const t = useT();
  const collapsible = shelf === "past";
  const [open, setOpen] = useState(!collapsible);
  const holdsSelection = builds.some((b) => b.id === selectedId);
  if (!builds.length) return null;
  const expanded = open || holdsSelection;
  return (
    <section data-testid={`shelf-${shelf}`} aria-labelledby={`shelf-${shelf}-title`}>
      <div className="mb-3 flex items-baseline gap-3">
        <h2 id={`shelf-${shelf}-title`} className="text-base font-semibold text-foreground-strong">
          {t(`self_build.shelf.${shelf}`)}
          <span className="ml-2 font-normal tabular-nums text-muted-foreground">{builds.length}</span>
        </h2>
        <span className="truncate text-sm text-muted-foreground">{t(`self_build.shelf.${shelf}_hint`)}</span>
        {collapsible && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={expanded}
            className="ml-auto inline-flex shrink-0 items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            {expanded ? t("self_build.hide_past") : fill(t("self_build.show_past"), { count: builds.length })}
            <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", expanded && "rotate-180")} aria-hidden />
          </button>
        )}
      </div>
      {expanded && (
        <ul className="space-y-2">
          {builds.map((build) => (
            <BuildRow
              key={build.id}
              build={build}
              selected={build.id === selectedId}
              onSelect={() => onSelect(build)}
              canBuild={canBuild(build)}
              blockedTitle={blockedTitle(build)}
              busy={busyId === build.id}
              onAction={onAction}
              limits={limits}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function BuildRow({
  build,
  selected,
  onSelect,
  canBuild,
  blockedTitle,
  busy,
  onAction,
  limits,
}: {
  build: Build;
  selected: boolean;
  onSelect: () => void;
  canBuild: boolean;
  blockedTitle?: string;
  busy: boolean;
  onAction: (build: Build, action: BuildAction) => void;
  limits: { trial_days: number; trial_uses: number } | undefined;
}) {
  const t = useT();
  const locale = useRunLocale();
  const trial = trialProgress(build, limits);
  const quiet = shelfOf(build) === "past";
  const ref = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView?.({ block: "nearest" });
  }, [selected]);
  const meta = useMemo(() => {
    const bits = [t(`self_build.kind.${build.kind}`)];
    if (quiet) bits.push(t(`self_build.state.${build.state}`));
    if (build.evidence.length > 1) bits.push(fill(t("self_build.seen"), { count: build.evidence.length }));
    bits.push(relativeTime(build.updated_ms, locale));
    return bits.join(" · ");
  }, [build, quiet, t, locale]);
  return (
    <li ref={ref}>
      <div
        role="button"
        tabIndex={0}
        data-testid="build-row"
        data-build-id={build.id}
        data-state={build.state}
        aria-pressed={selected}
        onClick={onSelect}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onSelect();
          }
        }}
        className={cn(
          "group flex cursor-pointer items-start gap-3 rounded-lg border px-4 py-3 transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          selected ? "border-border-strong bg-secondary" : "border-border bg-card hover:border-border-strong",
          quiet && !selected && "bg-transparent",
        )}
      >
        <span className={cn("mt-0.5", quiet ? "text-muted-foreground" : "text-foreground")}>
          <KindIcon kind={build.kind} />
        </span>
        <div className="min-w-0 flex-1">
          <p className={cn("line-clamp-2 text-[15px] leading-snug", quiet ? "text-muted-foreground" : "text-foreground-strong")}>
            {build.title}
          </p>
          <p className="mt-1 truncate text-sm text-muted-foreground">{meta}</p>
          {trial && (
            <div className="mt-2 flex items-center gap-3">
              <div className="h-1 w-32 overflow-hidden rounded-full bg-secondary" aria-hidden>
                <div className="h-full rounded-full bg-accent" style={{ width: `${Math.round(trial.share * 100)}%` }} />
              </div>
              <span className="truncate text-xs tabular-nums text-muted-foreground">
                {fill(t("self_build.trial_progress"), {
                  days: trial.days,
                  dayLimit: trial.dayLimit,
                  uses: trial.uses,
                  useLimit: trial.useLimit,
                })}
              </span>
            </div>
          )}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2.5">
          <LifecycleRail state={build.state} reached={reachedStep(build)} compact />
          {(build.state === "proposed" || build.state === "trial") && (
            <BuildActions build={build} canBuild={canBuild} blockedTitle={blockedTitle} busy={busy} onAction={onAction} />
          )}
        </div>
      </div>
    </li>
  );
}

// ------------------------------------------------------------------ calm states

function PickHint() {
  const t = useT();
  return (
    <div className="rounded-xl border border-dashed border-border px-6 py-10 text-center">
      <p className="mx-auto max-w-xs text-sm text-muted-foreground">{t("self_build.detail.select")}</p>
      <LoopLine className="mt-6 justify-center" />
    </div>
  );
}

const LOOP = ["notice", "decide", "build", "check", "trial", "keep"] as const;

function LoopLine({ className }: { className?: string }) {
  const t = useT();
  return (
    <ol className={cn("flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground", className)}>
      {LOOP.map((step, index) => (
        <li key={step} className="flex items-center gap-2">
          {index > 0 && <span aria-hidden className="text-border-strong">→</span>}
          <span>{t(`self_build.empty.loop.${step}`)}</span>
        </li>
      ))}
    </ol>
  );
}

function EmptyLoop() {
  const t = useT();
  return (
    <section data-testid="self-build-empty" className="mt-16 max-w-2xl">
      <h2 className="font-display text-xl text-foreground-strong">{t("self_build.empty.title")}</h2>
      <p className="mt-2 text-base leading-relaxed text-muted-foreground">{t("self_build.empty.body")}</p>
      <LoopLine className="mt-6" />
    </section>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return <div className="flex flex-1 items-center justify-center py-24">{children}</div>;
}

function ConfirmStop({ busy, onCancel, onConfirm }: { busy: boolean; onCancel: () => void; onConfirm: () => void }) {
  const t = useT();
  const cancel = useRef<HTMLButtonElement>(null);
  useEffect(() => cancel.current?.focus(), []);
  return (
    <div
      role="presentation"
      className="fixed inset-0 z-[110] flex items-center justify-center bg-background/60 p-4"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget && !busy) onCancel();
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && !busy) onCancel();
      }}
    >
      <section
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="stop-all-title"
        data-testid="stop-all-confirm"
        className="w-full max-w-sm rounded-xl border border-border bg-popover p-5 text-popover-foreground shadow-float"
      >
        <h2 id="stop-all-title" className="text-base font-semibold text-foreground-strong">
          {t("self_build.stop_confirm_title")}
        </h2>
        <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{t("self_build.stop_confirm_body")}</p>
        <div className="mt-5 flex justify-end gap-2">
          <button
            ref={cancel}
            type="button"
            disabled={busy}
            onClick={onCancel}
            className="h-8 rounded-md px-3 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {t("self_build.cancel")}
          </button>
          <button
            type="button"
            data-testid="stop-all-ok"
            disabled={busy}
            onClick={onConfirm}
            className="inline-flex h-8 items-center gap-1.5 rounded-md bg-destructive px-3 text-sm font-medium text-destructive-foreground hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
          >
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
            {t("self_build.stop_all")}
          </button>
        </div>
      </section>
    </div>
  );
}

export default SelfBuildView;
