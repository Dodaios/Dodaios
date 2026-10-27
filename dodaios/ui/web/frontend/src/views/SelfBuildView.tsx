/**
 * "Built for you": what the assistant notices the person keeps doing, and the
 * small helpers it builds to take that off them.
 *
 * Built like the settings and library pages of a desktop chat app: a title
 * with one sentence under it, one status pill that holds every page option,
 * a slim line for the state (learning, paused, off, stopped), then plain
 * lists in the order a person asks about them: what waits for my OK, what is
 * running for me, what has it noticed, and what is archived. A build opens as
 * a sheet on the right with its full case file (`BuildDetail`). An empty page
 * says in two sentences what will appear here and when.
 *
 * It never interrupts: no toast, no sound, no voice. Live through
 * `SelfBuildChanged` (hooks/useWebSocket.ts). docs/self-build.md.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ChevronDown, Loader2, Sparkles } from "lucide-react";
import { fill, useLocaleChunk, useT } from "@/i18n";
import { useRunLocale } from "@/components/runs/format";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { useSettingsJump } from "@/store/settingsJump";
import { useSelfBuildFocus } from "@/store/selfBuildFocus";
import {
  useBuildAction,
  useSelfBuildList,
  useSelfBuildNoticed,
  useSelfBuildPause,
  useSelfBuildSettings,
  useSetSocietyKillSwitch,
  useSocietyKillSwitch,
  type BuildAction,
} from "@/hooks/useSelfBuild";
import { SelfBuildApiError, shelfOf, trialProgress, type Build, type SelfBuildStatus } from "@/lib/selfBuildApi";
import { BuildActions } from "./selfBuild/BuildActions";
import { BuildDetail } from "./selfBuild/BuildDetail";
import { StatusBanner, heroTone, type BannerAction } from "./selfBuild/Hero";
import { Group, Row, Section } from "./selfBuild/List";
import { HowItWorks, NoticedSection } from "./selfBuild/Noticed";
import { StatusMenu } from "./selfBuild/StatusMenu";
import { KindIcon, relativeTime } from "./selfBuild/shared";

type Limits = { trial_days: number; trial_uses: number } | undefined;

export function SelfBuildView() {
  const ready = useLocaleChunk("self_build");
  const t = useT();
  const locale = useRunLocale();
  const list = useSelfBuildList();
  const noticed = useSelfBuildNoticed();
  const settings = useSelfBuildSettings();
  const kill = useSocietyKillSwitch();
  const setKill = useSetSocietyKillSwitch();
  const pause = useSelfBuildPause();
  const setActive = useEventStore((s) => s.setActiveSection);
  const act = useBuildAction();
  const [selectedId, setSelectedId] = useState<string | null>(() => useSelfBuildFocus.getState().take());
  const [error, setError] = useState<string | null>(null);
  const [confirmStop, setConfirmStop] = useState(false);
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
  const hasNeeds = (noticed.data?.needs.length ?? 0) > 0;
  const nothingYet = builds.length === 0 && !hasNeeds;

  const bannerAction: BannerAction | undefined =
    tone === "paused"
      ? { label: t("self_build.resume"), onClick: () => pause.mutate(false), busy: pause.isPending, testId: "self-build-resume" }
      : tone === "off"
        ? { label: t("self_build.notes.turn_on"), onClick: openSettings, testId: "self-build-turn-on" }
        : tone === "stopped"
          ? { label: t("self_build.notes.release"), onClick: () => setKill.mutate(false), busy: setKill.isPending, testId: "self-build-release" }
          : undefined;

  return (
    <div data-testid="self-build-view" className="flex h-full min-h-0 flex-col overflow-y-auto">
      <div className="mx-auto w-full max-w-[760px] px-6 pb-16 pt-12 sm:px-8">
        <header className="flex items-start gap-6">
          <div className="min-w-0 flex-1">
            <h1 className="font-display text-[26px] font-semibold leading-tight tracking-[-0.02em] text-foreground-strong">
              {t("self_build.title")}
            </h1>
            <p className="mt-1.5 max-w-[56ch] text-[15px] leading-relaxed text-muted-foreground">{t("self_build.page.subtitle")}</p>
          </div>
          <StatusMenu
            tone={tone}
            enabled={Boolean(status?.enabled)}
            paused={Boolean(status?.paused)}
            pauseBusy={pause.isPending}
            onPause={(next) => pause.mutate(next)}
            onSettings={openSettings}
            onStopAll={stopped ? undefined : () => setConfirmStop(true)}
          />
        </header>

        {list.isPending ? (
          <Centered><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-label={t("self_build.loading")} /></Centered>
        ) : unavailable || list.error ? (
          <p role="alert" className="mt-10 text-base text-muted-foreground">{t("self_build.error.unavailable")}</p>
        ) : (
          <>
            {tone && <StatusBanner tone={tone} quiet={noticed.data?.quiet_start} locale={locale} action={bannerAction} />}
            <StateNotes status={status} stopped={stopped} />
            {error && (
              <p role="alert" className="mt-4 rounded-lg border border-destructive/40 px-3 py-2 text-sm text-destructive">
                {error}
              </p>
            )}

            {nothingYet && <EmptyState days={noticed.data?.threshold.days ?? 3} once={noticed.data?.once ?? 0} />}

            {groups.waiting.length > 0 && (
              <Section id="waiting" title={t("self_build.shelf.waiting")} count={groups.waiting.length}>
                <Group>
                  {groups.waiting.map((build) => (
                    <Row
                      key={build.id}
                      data={{ "build-id": build.id, state: build.state }}
                      selected={build.id === selectedId}
                      onClick={() => select(build)}
                      icon={<KindIcon kind={build.kind} />}
                      title={build.title}
                      sub={whyOf(build) || t(`self_build.suggested.${build.kind}`)}
                      right={
                        <BuildActions
                          build={build}
                          canBuild={canBuild(build)}
                          blockedTitle={blockedTitle(build)}
                          busy={busyId === build.id}
                          onAction={onAction}
                        />
                      }
                    />
                  ))}
                </Group>
              </Section>
            )}

            {groups.live.length + groups.kept.length > 0 && (
              <Section id="live" title={t("self_build.shelf.live")} count={groups.live.length + groups.kept.length}>
                <Group>
                  {[...groups.live, ...groups.kept].map((build) => (
                    <BuildRow
                      key={build.id}
                      build={build}
                      selected={build.id === selectedId}
                      onSelect={() => select(build)}
                      busy={busyId === build.id}
                      onAction={onAction}
                      limits={limits}
                      locale={locale}
                    />
                  ))}
                </Group>
              </Section>
            )}

            <NoticedSection
              data={noticed.data}
              locale={locale}
              paused={Boolean(status?.paused) || stopped}
              onOpenBuild={(id) => setSelectedId(id)}
            />

            {groups.past.length > 0 && (
              <PastSection
                builds={groups.past}
                selectedId={selectedId}
                onSelect={select}
                busyId={busyId}
                onAction={onAction}
                limits={limits}
                locale={locale}
              />
            )}

            <HowItWorks center={nothingYet} />
          </>
        )}
      </div>

      {confirmStop && (
        <ConfirmStop
          busy={setKill.isPending}
          onCancel={() => setConfirmStop(false)}
          onConfirm={() => {
            setKill.mutate(true);
            setConfirmStop(false);
          }}
        />
      )}

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

/** Machine-readable markers for the states the banner already explains in words. */
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

/** Nothing built and nothing repeated yet: say what will appear here, and when. */
function EmptyState({ days, once }: { days: number; once: number }) {
  const t = useT();
  return (
    <div data-testid="noticed-empty" className="mt-16 flex flex-col items-center text-center">
      <span aria-hidden className="flex h-12 w-12 items-center justify-center rounded-2xl bg-secondary text-foreground">
        <Sparkles className="h-5 w-5" strokeWidth={1.6} />
      </span>
      <p className="mt-5 text-base font-medium text-foreground-strong">{t("self_build.page.empty_title")}</p>
      <p className="mt-1.5 max-w-[44ch] text-sm leading-relaxed text-muted-foreground">
        {fill(t("self_build.page.empty_body"), { days })}
      </p>
      {once > 0 && (
        <p className="mt-3 text-xs text-foreground-faint">
          {fill(t(once === 1 ? "self_build.noticed.once_one" : "self_build.noticed.once_other"), { count: once })}
        </p>
      )}
    </div>
  );
}

/** The first sentence of the case: the plain "why" under a suggestion. */
function whyOf(build: Build): string {
  const line = (build.case || "").split("\n").map((l) => l.trim()).find(Boolean) ?? "";
  return line.length > 160 ? `${line.slice(0, 159).trimEnd()}…` : line;
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
  const sub = useMemo(() => {
    const bits = [t(`self_build.kind.${build.kind}`)];
    if (trial) {
      bits.push(fill(t("self_build.trial_progress"), { days: trial.days, dayLimit: trial.dayLimit, uses: trial.uses, useLimit: trial.useLimit }));
    } else {
      bits.push(t(`self_build.state.${build.state}`));
      if (build.uses > 0) bits.push(fill(t("self_build.detail.uses"), { count: build.uses }));
      bits.push(relativeTime(build.last_used_ms || build.updated_ms, locale));
    }
    return bits.join(" · ");
  }, [build, t, locale, trial]);
  return (
    <Row
        rowRef={ref}
        data={{ "build-id": build.id, state: build.state }}
        selected={selected}
        onClick={onSelect}
        muted={quiet}
        icon={working ? <Loader2 className="h-4 w-4 animate-spin" /> : <KindIcon kind={build.kind} />}
        title={build.title}
        sub={sub}
        right={
          build.state === "trial" || build.state === "kept" || build.state === "archived" ? (
            <BuildActions build={build} canBuild={false} busy={busy} onAction={onAction} />
          ) : undefined
        }
      />
  );
}

function PastSection({
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
    <Section
      id="past"
      title={t("self_build.shelf.past")}
      count={builds.length}
      aside={
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={expanded}
          className="inline-flex items-center gap-1 rounded-sm text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {expanded ? t("self_build.hide_past") : fill(t("self_build.show_past"), { count: builds.length })}
          <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", expanded && "rotate-180")} aria-hidden />
        </button>
      }
    >
      {expanded && (
        <Group>
          {builds.map((build) => (
            <BuildRow
              key={build.id}
              build={build}
              selected={build.id === selectedId}
              onSelect={() => onSelect(build)}
              busy={busyId === build.id}
              onAction={onAction}
              limits={limits}
              locale={locale}
            />
          ))}
        </Group>
      )}
    </Section>
  );
}

// ------------------------------------------------------------------ sheet, confirm

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
