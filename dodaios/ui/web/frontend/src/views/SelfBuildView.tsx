/**
 * "Built for you": what the assistant notices the person keeps doing, and the
 * small helpers it builds to take that off them.
 *
 * One reading column, top to bottom, in the order a person asks about it:
 * what is this and is it working (the hero), what needs me (suggestions),
 * what is running for me (trials, builds in progress), what has it noticed so
 * far (the repeats it is counting), what did I keep, and what is gone. A
 * build opens as a sheet on the right with its full case file
 * (`BuildDetail`). While nothing is built, the page teaches the idea in three
 * steps instead of standing empty.
 *
 * It never interrupts: no toast, no sound, no voice. Live through
 * `SelfBuildChanged` (hooks/useWebSocket.ts). docs/self-build.md.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight, Loader2, OctagonX, Pause, Play, Settings2 } from "lucide-react";
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
  useSelfBuildNoticed,
  useSelfBuildPause,
  useSelfBuildSettings,
  useSetSocietyKillSwitch,
  useSocietyKillSwitch,
  type BuildAction,
} from "@/hooks/useSelfBuild";
import {
  SelfBuildApiError,
  shelfOf,
  trialProgress,
  type Build,
  type BuildDigest,
  type SelfBuildStatus,
} from "@/lib/selfBuildApi";
import { BuildActions } from "./selfBuild/BuildActions";
import { BuildDetail } from "./selfBuild/BuildDetail";
import { Hero, heroTone, type HeroTone } from "./selfBuild/Hero";
import { HowItWorks, NoticedSection, SectionHead } from "./selfBuild/Noticed";
import { KindIcon, relativeTime } from "./selfBuild/shared";

type Limits = { trial_days: number; trial_uses: number } | undefined;

export function SelfBuildView() {
  const ready = useLocaleChunk("self_build");
  const t = useT();
  const locale = useRunLocale();
  const list = useSelfBuildList();
  const digest = useSelfBuildDigest(24);
  const noticed = useSelfBuildNoticed();
  const settings = useSelfBuildSettings();
  const kill = useSocietyKillSwitch();
  const setKill = useSetSocietyKillSwitch();
  const pause = useSelfBuildPause();
  const setActive = useEventStore((s) => s.setActiveSection);
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
  const stopped = kill.data === true;
  const tone = heroTone(status, stopped);
  // Accepting starts a build, so it waits while building is paused.
  const canBuild = (build: Build) => Boolean(status?.builders.includes(build.kind)) && !status?.paused;
  const blockedTitle = (build: Build) =>
    status?.paused ? t("self_build.notes.paused") : !status?.builders.includes(build.kind) ? t("self_build.no_builder") : undefined;

  const groups = useMemo(() => {
    const by = { waiting: [] as Build[], live: [] as Build[], kept: [] as Build[], past: [] as Build[] };
    for (const build of builds) {
      const shelf = shelfOf(build);
      if (shelf === "waiting") by.waiting.push(build);
      else if (shelf === "trial" || shelf === "working") by.live.push(build);
      else if (shelf === "kept") by.kept.push(build);
      else by.past.push(build);
    }
    // Trials first (they can be kept or undone), then what is still being built.
    by.live.sort((a, b) => Number(b.state === "trial") - Number(a.state === "trial"));
    return by;
  }, [builds]);

  const onAction = (build: Build, action: BuildAction) => {
    setError(null);
    act.mutate(
      { id: build.id, action },
      { onError: (err) => setError(fill(t("self_build.error.action"), { detail: err.message })) },
    );
  };
  const openSettings = () => {
    useSettingsJump.getState().request("self-build");
    setActive("settings");
  };
  const select = (build: Build) => setSelectedId(build.id === selectedId ? null : build.id);
  const busyId = act.isPending ? act.variables?.id ?? null : null;

  if (!ready) return <Centered><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden /></Centered>;

  const unavailable = list.error instanceof SelfBuildApiError && list.error.status === 503;
  const helpersLive = groups.live.filter((b) => b.state === "trial").length + groups.kept.length;
  const nothingBuilt = builds.length === 0;

  const heroAction =
    tone === "paused"
      ? { label: t("self_build.resume"), onClick: () => pause.mutate(false), busy: pause.isPending, testId: "self-build-resume", icon: <Play className="h-4 w-4" aria-hidden /> }
      : tone === "off"
        ? { label: t("self_build.notes.turn_on"), onClick: openSettings, testId: "self-build-turn-on" }
        : tone === "stopped"
          ? { label: t("self_build.notes.release"), onClick: () => setKill.mutate(false), busy: setKill.isPending, testId: "self-build-release" }
          : undefined;

  return (
    <div data-testid="self-build-view" className="flex h-full min-h-0 flex-col overflow-y-auto">
      <div className="mx-auto flex w-full max-w-[1000px] flex-1 flex-col px-6 pb-12 pt-10 sm:px-10">
        <TopBar tone={tone} paused={Boolean(status?.paused)} enabled={Boolean(status?.enabled)} onSettings={openSettings} />

        {list.isPending ? (
          <Centered><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-label={t("self_build.loading")} /></Centered>
        ) : unavailable || list.error ? (
          <p role="alert" className="mt-10 text-base text-muted-foreground">{t("self_build.error.unavailable")}</p>
        ) : (
          <>
            {tone && (
              <Hero
                tone={tone}
                status={status}
                quiet={noticed.data?.quiet_start}
                waiting={groups.waiting.length}
                live={helpersLive}
                locale={locale}
                action={heroAction}
              />
            )}
            <StateNotes status={status} stopped={stopped} />
            <DigestLine digest={digest.data} />
            {error && (
              <p role="alert" className="mt-4 rounded-lg border border-destructive/40 px-3 py-2 text-sm text-destructive">
                {error}
              </p>
            )}

            {nothingBuilt && <HowItWorks />}

            {groups.waiting.length > 0 && (
              <section data-testid="shelf-waiting" aria-labelledby="shelf-waiting-title" className="mt-12">
                <SectionHead id="shelf-waiting-title" title={t("self_build.shelf.waiting")} hint={t("self_build.shelf.waiting_hint")} count={groups.waiting.length} />
                <ul className="space-y-3">
                  {groups.waiting.map((build) => (
                    <ProposalCard
                      key={build.id}
                      build={build}
                      selected={build.id === selectedId}
                      onSelect={() => select(build)}
                      canBuild={canBuild(build)}
                      blockedTitle={blockedTitle(build)}
                      busy={busyId === build.id}
                      onAction={onAction}
                      locale={locale}
                    />
                  ))}
                </ul>
              </section>
            )}

            {groups.live.length > 0 && (
              <Shelf id="live" title={t("self_build.shelf.live")} hint={t("self_build.shelf.live_hint")} count={groups.live.length}>
                {groups.live.map((build) => (
                  <BuildRow key={build.id} build={build} selected={build.id === selectedId} onSelect={() => select(build)} busy={busyId === build.id} onAction={onAction} limits={limits} locale={locale} />
                ))}
              </Shelf>
            )}

            <NoticedSection
              data={noticed.data}
              locale={locale}
              paused={Boolean(status?.paused) || stopped}
              onOpenBuild={(id) => setSelectedId(id)}
            />

            {groups.kept.length > 0 && (
              <Shelf id="kept" title={t("self_build.shelf.kept")} hint={t("self_build.shelf.kept_hint")} count={groups.kept.length}>
                {groups.kept.map((build) => (
                  <BuildRow key={build.id} build={build} selected={build.id === selectedId} onSelect={() => select(build)} busy={busyId === build.id} onAction={onAction} limits={limits} locale={locale} />
                ))}
              </Shelf>
            )}

            {groups.past.length > 0 && (
              <PastShelf builds={groups.past} selectedId={selectedId} onSelect={select} busyId={busyId} onAction={onAction} limits={limits} locale={locale} />
            )}

            {!nothingBuilt && <HowItWorks compact />}
          </>
        )}

        <Footer stopped={stopped} busy={setKill.isPending} onStop={() => setKill.mutate(true)} />
      </div>

      {selected && (
        <DetailSheet onClose={() => setSelectedId(null)}>
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
        </DetailSheet>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ top bar

function TopBar({
  tone,
  paused,
  enabled,
  onSettings,
}: {
  tone: HeroTone | null;
  paused: boolean;
  enabled: boolean;
  onSettings: () => void;
}) {
  const t = useT();
  const pause = useSelfBuildPause();
  return (
    <header className="flex flex-wrap items-center gap-x-4 gap-y-3">
      <div className="min-w-0 flex-1">
        <h1 className="font-display text-xl font-semibold text-foreground-strong">{t("self_build.title")}</h1>
      </div>
      {tone && (
        <span data-testid="self-build-status" data-tone={tone} className="inline-flex items-center gap-2 text-sm text-muted-foreground">
          <span
            aria-hidden
            className={cn(
              "h-2 w-2 rounded-full",
              tone === "running" && "bg-success",
              tone === "silent" && "bg-accent",
              tone === "paused" && "bg-warning",
              tone === "stopped" && "bg-destructive",
              tone === "off" && "bg-border-strong",
            )}
          />
          {t(`self_build.status.${tone}`)}
        </span>
      )}
      {enabled && (
        <button
          type="button"
          data-testid="self-build-pause"
          aria-pressed={paused}
          title={t("self_build.pause_hint")}
          disabled={pause.isPending}
          onClick={() => pause.mutate(!paused)}
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border-strong px-3 text-sm font-medium text-foreground transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
        >
          {paused ? <Play className="h-3.5 w-3.5" aria-hidden /> : <Pause className="h-3.5 w-3.5" aria-hidden />}
          {paused ? t("self_build.resume") : t("self_build.pause")}
        </button>
      )}
      <button
        type="button"
        onClick={onSettings}
        aria-label={t("self_build.settings")}
        title={t("self_build.settings")}
        data-testid="self-build-settings"
        className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Settings2 className="h-4 w-4" aria-hidden />
      </button>
    </header>
  );
}

/** Machine-readable markers for the states the hero already explains in words. */
function StateNotes({ status, stopped }: { status: SelfBuildStatus | undefined; stopped: boolean }) {
  return (
    <>
      {stopped && <span data-testid="note-stopped" hidden />}
      {status && !status.enabled && <span data-testid="note-off" hidden />}
      {status?.enabled && status.paused && <span data-testid="note-paused" hidden />}
      {status?.enabled && !status.paused && status.silent && <span data-testid="note-silent" hidden />}
    </>
  );
}

// ------------------------------------------------------------------ digest

/** What changed since yesterday, as one quiet line; nothing when nothing did. */
function DigestLine({ digest }: { digest: BuildDigest | undefined }) {
  const t = useT();
  if (!digest) return null;
  const counts = digest.counts;
  const built = (counts.trial ?? 0) + (counts.building ?? 0) + (counts.proving ?? 0);
  const parts: [string, number][] = [
    ["proposed", counts.proposed ?? 0],
    ["built", built],
    ["kept", counts.kept ?? 0],
    ["archived", counts.archived ?? 0],
    ["undone", counts.undone ?? 0],
  ];
  const shown = parts.filter(([, n]) => n > 0);
  if (!shown.length) return null;
  return (
    <p data-testid="self-build-digest" className="mt-4 flex flex-wrap items-baseline gap-x-2 gap-y-1 px-1 text-sm text-muted-foreground">
      <span className="font-medium">{t("self_build.digest.label")}</span>
      {shown.map(([key, n]) => (
        <span key={key} className="text-foreground">
          <span aria-hidden className="mr-2 text-border-strong">·</span>
          {fill(t(`self_build.digest.${key}`), { count: n })}
        </span>
      ))}
    </p>
  );
}

// ------------------------------------------------------------------ suggestions

/** The first sentence of the case: the plain "why" under a suggestion. */
function whyOf(build: Build): string {
  const line = (build.case || "").split("\n").map((l) => l.trim()).find(Boolean) ?? "";
  return line.length > 220 ? `${line.slice(0, 219).trimEnd()}…` : line;
}

function ProposalCard({
  build,
  selected,
  onSelect,
  canBuild,
  blockedTitle,
  busy,
  onAction,
  locale,
}: {
  build: Build;
  selected: boolean;
  onSelect: () => void;
  canBuild: boolean;
  blockedTitle?: string;
  busy: boolean;
  onAction: (build: Build, action: BuildAction) => void;
  locale: string;
}) {
  const t = useT();
  const why = whyOf(build);
  return (
    <li>
      <div
        data-testid="build-row"
        data-build-id={build.id}
        data-state={build.state}
        data-selected={selected || undefined}
        onClick={onSelect}
        className={cn(
          "cursor-pointer rounded-xl border bg-card px-6 py-5 transition-colors",
          selected ? "border-accent/60" : "border-border hover:border-border-strong",
        )}
      >
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <KindIcon kind={build.kind} />
          <span>{t(`self_build.suggested.${build.kind}`)}</span>
          <span aria-hidden>·</span>
          <span>{relativeTime(build.created_ms, locale)}</span>
        </p>
        <p className="mt-2 text-lg font-medium leading-snug text-foreground-strong">{build.title}</p>
        {why && <p className="mt-1.5 line-clamp-2 text-base leading-relaxed text-muted-foreground">{why}</p>}
        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
          <BuildActions build={build} canBuild={canBuild} blockedTitle={blockedTitle} busy={busy} onAction={onAction} size="default" />
          <span className="text-sm text-muted-foreground">
            {build.evidence.length > 0
              ? fill(t(build.evidence.length === 1 ? "self_build.based_on_one" : "self_build.based_on_other"), { count: build.evidence.length })
              : ""}
          </span>
          <OpenButton selected={selected} onSelect={onSelect} className="ml-auto" />
        </div>
      </div>
    </li>
  );
}

/** The keyboard way into a build's case file (the whole card also opens it on click). */
function OpenButton({ selected, onSelect, className }: { selected: boolean; onSelect: () => void; className?: string }) {
  const t = useT();
  return (
    <button
      type="button"
      data-testid="build-open"
      aria-expanded={selected}
      onClick={(event) => {
        event.stopPropagation();
        onSelect();
      }}
      className={cn(
        "inline-flex h-8 items-center gap-0.5 rounded-md px-2 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
    >
      {t("self_build.details")}
      <ChevronRight className="h-3.5 w-3.5" aria-hidden />
    </button>
  );
}

// ------------------------------------------------------------------ shelves

function Shelf({ id, title, hint, count, children }: { id: string; title: string; hint: string; count: number; children: ReactNode }) {
  return (
    <section data-testid={`shelf-${id}`} aria-labelledby={`shelf-${id}-title`} className="mt-12">
      <SectionHead id={`shelf-${id}-title`} title={title} hint={hint} count={count} />
      <ul className="overflow-hidden rounded-xl border border-border bg-card">{children}</ul>
    </section>
  );
}

function PastShelf({
  builds,
  selectedId,
  onSelect,
  busyId,
  onAction,
  limits,
  locale,
}: {
  builds: Build[];
  selectedId: string | null;
  onSelect: (build: Build) => void;
  busyId: string | null;
  onAction: (build: Build, action: BuildAction) => void;
  limits: Limits;
  locale: string;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const expanded = open || builds.some((b) => b.id === selectedId);
  return (
    <section data-testid="shelf-past" aria-labelledby="shelf-past-title" className="mt-12">
      <div className="mb-3 flex items-baseline gap-3">
        <h2 id="shelf-past-title" className="text-lg font-semibold text-foreground-strong">
          {t("self_build.shelf.past")}
          <span className="ml-2 font-normal tabular-nums text-muted-foreground">{builds.length}</span>
        </h2>
        <p className="hidden truncate text-sm text-muted-foreground sm:block">{t("self_build.shelf.past_hint")}</p>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={expanded}
          className="ml-auto inline-flex shrink-0 items-center gap-1 rounded-sm text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {expanded ? t("self_build.hide_past") : fill(t("self_build.show_past"), { count: builds.length })}
          <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", expanded && "rotate-180")} aria-hidden />
        </button>
      </div>
      {expanded && (
        <ul className="overflow-hidden rounded-xl border border-border">
          {builds.map((build) => (
            <BuildRow key={build.id} build={build} selected={build.id === selectedId} onSelect={() => onSelect(build)} busy={busyId === build.id} onAction={onAction} limits={limits} locale={locale} />
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
  busy,
  onAction,
  limits,
  locale,
}: {
  build: Build;
  selected: boolean;
  onSelect: () => void;
  busy: boolean;
  onAction: (build: Build, action: BuildAction) => void;
  limits: Limits;
  locale: string;
}) {
  const t = useT();
  const trial = trialProgress(build, limits);
  const shelf = shelfOf(build);
  const quiet = shelf === "past";
  const working = shelf === "working";
  const ref = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView?.({ block: "nearest" });
  }, [selected]);
  const meta = useMemo(() => {
    const bits = [t(`self_build.kind.${build.kind}`), t(`self_build.state.${build.state}`)];
    if (build.uses > 0) bits.push(fill(t("self_build.detail.uses"), { count: build.uses }));
    bits.push(relativeTime(build.last_used_ms || build.updated_ms, locale));
    return bits.join(" · ");
  }, [build, t, locale]);
  return (
    <li ref={ref} className="border-t border-border first:border-t-0">
      <div
        data-testid="build-row"
        data-build-id={build.id}
        data-state={build.state}
        data-selected={selected || undefined}
        onClick={onSelect}
        className={cn(
          "flex cursor-pointer flex-wrap items-center gap-x-4 gap-y-3 px-5 py-4 transition-colors",
          selected ? "bg-accent/10" : "hover:bg-secondary/60",
        )}
      >
        <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-secondary", quiet ? "text-muted-foreground" : "text-foreground")}>
          {working ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <KindIcon kind={build.kind} />}
        </span>
        <div className="min-w-0 flex-1 basis-[260px]">
          <p className={cn("line-clamp-2 text-base leading-snug", quiet ? "text-muted-foreground" : "text-foreground-strong")}>{build.title}</p>
          <p className="mt-0.5 truncate text-sm text-muted-foreground">{meta}</p>
          {trial && (
            <div className="mt-2 flex items-center gap-3">
              <div className="h-1 w-32 overflow-hidden rounded-full bg-surface-raised" aria-hidden>
                <div className="h-full rounded-full bg-accent" style={{ width: `${Math.round(trial.share * 100)}%` }} />
              </div>
              <span className="truncate text-xs tabular-nums text-muted-foreground">
                {fill(t("self_build.trial_progress"), { days: trial.days, dayLimit: trial.dayLimit, uses: trial.uses, useLimit: trial.useLimit })}
              </span>
            </div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {(build.state === "trial" || build.state === "kept") && (
            <BuildActions build={build} canBuild={false} busy={busy} onAction={onAction} />
          )}
          <OpenButton selected={selected} onSelect={onSelect} />
        </div>
      </div>
    </li>
  );
}

// ------------------------------------------------------------------ sheet, footer

function DetailSheet({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    panel.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-[100] flex justify-end" data-testid="build-sheet">
      <div role="presentation" className="absolute inset-0 bg-background/50" onPointerDown={onClose} />
      <div
        ref={panel}
        tabIndex={-1}
        className="relative flex h-full w-full max-w-[520px] flex-col p-3 outline-none motion-safe:animate-in motion-safe:slide-in-from-right-4 [&>article]:h-full [&>article]:shadow-float"
      >
        {children}
      </div>
    </div>
  );
}

function Footer({ stopped, busy, onStop }: { stopped: boolean; busy: boolean; onStop: () => void }) {
  const t = useT();
  const [confirm, setConfirm] = useState(false);
  if (stopped) return null;
  return (
    <footer className="mt-16 flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-border pt-5 text-sm text-muted-foreground">
      <span className="flex-1">{t("self_build.stop_footer")}</span>
      <button
        type="button"
        data-testid="society-stop-all"
        title={t("self_build.stop_all_hint")}
        onClick={() => setConfirm(true)}
        className="inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-sm text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <OctagonX className="h-4 w-4" aria-hidden />
        {t("self_build.stop_all")}
      </button>
      {confirm && (
        <ConfirmStop
          busy={busy}
          onCancel={() => setConfirm(false)}
          onConfirm={() => {
            onStop();
            setConfirm(false);
          }}
        />
      )}
    </footer>
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
