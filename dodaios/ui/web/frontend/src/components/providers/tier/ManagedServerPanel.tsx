import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Brain, Check, ChevronDown, Download, Loader2, Mic, Play, Search, Square, Volume2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BrandedSelect } from "@/components/ui/select";
import { managedServerInstall, managedServerModelCatalog, managedServerPreflight, managedServerSetup, managedServerStart, managedServerStatus, managedServerStop, managedServerUninstall, modelPullStatus, startModelPull, type ManagedModelCatalog, type ManagedServerRuntime, type ManagedInstallProgress, type ManagedPreflight, type ProviderDescriptor, switchRealtimeProvider } from "@/hooks/useProviders";
import { cn } from "@/lib/utils";
import { useT } from "@/i18n";
import { managedRuntimeBadge } from "./LocalRuntimePanel";
import { LibraryBrowser } from "./OllamaPanels";

/**
 * One-click managed install for the self-hosted realtime server (the card
 * that used to require a terminal, a venv, and a hand-written launch
 * command). Flow: preflight (honest hardware/tier/brain verdict or the
 * 12 GB-floor blocker) → one confirm with download size and expected
 * latency in view → poll-shaped progress → the card's fail-closed readiness
 * flips server-side. Every sentence of substance comes from the server and
 * renders verbatim; only the chrome is localized.
 */
export function ManagedServerPanel({
  descriptor,
  onChanged,
}: {
  descriptor: ProviderDescriptor;
  onChanged: () => void;
}) {
  const t = useT();
  const status = descriptor.managed_server;
  const [preflight, setPreflight] = useState<ManagedPreflight | null>(null);
  const [progress, setProgress] = useState<ManagedInstallProgress | null>(null);
  const [runtime, setRuntime] = useState<ManagedServerRuntime | null>(null);
  const [catalog, setCatalog] = useState<ManagedModelCatalog | null>(null);
  const [selectedBrain, setSelectedBrain] = useState("");
  const [selectedVoice, setSelectedVoice] = useState("");
  const [voiceQuery, setVoiceQuery] = useState("");
  const [setupBusy, setSetupBusy] = useState(false);
  const [setupNote, setSetupNote] = useState<string | null>(null);
  const [libraryBusy, setLibraryBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [lifecycleBusy, setLifecycleBusy] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const running = Boolean(progress?.running);

  useEffect(() => {
    if (!running) return;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const next = await managedServerStatus();
        if (cancelled) return;
        setProgress(next.progress);
        setRuntime(next.runtime ?? null);
        if (!next.progress.running) {
          window.clearInterval(timer);
          if (next.progress.phase === "error") {
            setError(next.progress.error || t("apikeys_view.install_failed_fallback"));
          }
          onChanged();
        }
      } catch (err) {
        if (cancelled) return;
        window.clearInterval(timer);
        setError(err instanceof Error ? err.message : String(err));
        setProgress(null);
      }
    }, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [running, onChanged]);

  // Idle runtime poll: the panel used to only look at the server DURING an
  // install, so a crashed/stopped/foreign server rendered as whatever the
  // last install left behind. One fetch on mount, then a slow heartbeat.
  const installed = Boolean(status?.ready);
  useEffect(() => {
    if (running || !installed) return;
    let cancelled = false;
    let timer: number | undefined;
    const read = async () => {
      let delay = 20_000;
      try {
        const next = await managedServerStatus();
        if (!cancelled) setRuntime(next.runtime ?? null);
        if (next.runtime?.boot?.starting || next.runtime?.ready === false || setupBusy || lifecycleBusy) {
          delay = 1500;
        }
      } catch {
        if (!cancelled) setRuntime(null);
        delay = 5000;
      } finally {
        if (!cancelled) timer = window.setTimeout(read, delay + Math.random() * 500);
      }
    };
    void read();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [running, installed, setupBusy, lifecycleBusy]);

  if (!status) return null;

  // The Remove control must survive a PARTIAL state: after a failed
  // uninstall (or interrupted install) `ready` is false but gigabytes are
  // still on disk — gating removal on `ready` would strand them forever.
  const anythingOnDisk = Object.values(status.components ?? {}).some(Boolean);

  const check = async () => {
    setError(null);
    setChecking(true);
    try {
      setPreflight(await managedServerPreflight());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setChecking(false);
    }
  };

  const startInstall = async () => {
    setError(null);
    try {
      // A fixable blocked brain is CONFIRMED as "ollama": the engine sets it
      // up first and its post-setup re-check must match this confirmation.
      const first = await managedServerInstall(
        preflight?.brain_fixable ? "ollama" : preflight?.brain?.kind,
        selectedBrain,
        selectedVoice,
      );
      setProgress(first);
      // A failure BEFORE the first poll tick (fast preflight error inside
      // the engine thread) would otherwise never render: the polling
      // effect only runs while `running` is true.
      if (!first.running && first.phase === "error" && first.error) {
        setError(first.error);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const remove = async () => {
    if (!confirmRemove) {
      setConfirmRemove(true);
      return;
    }
    setConfirmRemove(false);
    setError(null);
    try {
      await managedServerUninstall();
      setPreflight(null);
      setProgress(null);
      setRuntime(null);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const startServer = async () => {
    setError(null);
    setLifecycleBusy(true);
    try {
      setRuntime(await managedServerStart());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLifecycleBusy(false);
    }
  };

  const loadCatalog = useCallback(async () => {
    try {
      const next = await managedServerModelCatalog();
      setCatalog(next);
      setSelectedBrain((current) =>
        current ||
        next.brain.current ||
        next.brain.models.find((choice) => choice.recommended && choice.fits)?.id ||
        next.brain.models.find((choice) => choice.fits)?.id ||
        "",
      );
      setSelectedVoice((current) =>
        current ||
        next.current ||
        next.models.find((choice) => choice.recommended && choice.selectable)?.id ||
        next.models.find((choice) => choice.selectable)?.id ||
        "",
      );
    } catch (err) {
      setCatalog(null);
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    if (running) return;
    void loadCatalog();
  }, [running, loadCatalog]);

  const downloadBrain = async (model: string) => {
    await startModelPull("ollama", model);
    for (;;) {
      const pull = await modelPullStatus("ollama", model);
      if (pull.state === "done") return;
      if (pull.state === "error") {
        throw new Error(pull.message || t("apikeys_view.model_download_failed_fallback"));
      }
      setSetupNote(`${model}: ${Math.round(pull.percent ?? 0)}%`);
      await new Promise((resolve) => window.setTimeout(resolve, 2500));
    }
  };

  const applySetup = async (
    brainModel = selectedBrain,
    downloadFirst = false,
    voiceModel = selectedVoice,
  ) => {
    if (!brainModel || !voiceModel) return;
    setError(null);
    setSetupNote(t("apikeys_view.managed_setup_testing"));
    setSetupBusy(true);
    try {
      const choice = catalog?.brain.models.find((item) => item.id === brainModel);
      if (downloadFirst || (choice && !choice.installed)) {
        // Download through the SAME pull machinery the Ollama card uses,
        // then adopt — never adopt a model the server cannot serve yet.
        await downloadBrain(brainModel);
      }
      const result = await managedServerSetup(brainModel, voiceModel);
      if (!descriptor.active) {
        await switchRealtimeProvider(descriptor.id, descriptor.experimental === true);
      }
      window.dispatchEvent(new CustomEvent("jarvis:realtime-switched"));
      const latency = result.smoke.first_audio_ms;
      setSelectedBrain(brainModel);
      setSelectedVoice(voiceModel);
      setSetupNote(
        latency === null
          ? t("apikeys_view.managed_setup_complete")
          : t("apikeys_view.managed_setup_complete_ms").replace(
              "{0}",
              String(latency),
            ),
      );
      await loadCatalog();
      onChanged();
    } catch (err) {
      setSetupNote(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSetupBusy(false);
      setLibraryBusy(null);
    }
  };

  const applyCatalogModel = async (model: string, installedModel: boolean) => {
    setLibraryBusy(model);
    setSelectedBrain(model);
    if (!installed) {
      try {
        if (!installedModel) await downloadBrain(model);
        setSetupNote(t("apikeys_view.managed_catalog_selected"));
        await loadCatalog();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLibraryBusy(null);
      }
      return;
    }
    await applySetup(model, !installedModel);
  };

  const applyVoiceChoice = async (choice: ManagedModelCatalog["models"][number]) => {
    if (!choice.selectable || !selectedBrain) return;
    setSelectedVoice(choice.id);
    setError(null);
    setSetupNote(null);
    if (!installed) {
      setSetupNote(t("apikeys_view.managed_catalog_selected"));
      return;
    }
    if (choice.runtime_ready === false) {
      setSetupBusy(true);
      try {
        // A runtime-compatible model whose optional package is absent uses the
        // existing resumable managed installer. It stops the owned server,
        // installs the pinned adapter dependency, applies compatibility
        // patches, downloads this checkpoint, and only commits after smoke.
        const first = await managedServerInstall(undefined, selectedBrain, choice.id);
        setProgress(first);
        if (!first.running && first.phase === "error" && first.error) {
          setError(first.error);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setSetupBusy(false);
      }
      return;
    }
    await applySetup(selectedBrain, false, choice.id);
  };

  const stopServer = async () => {
    setError(null);
    setLifecycleBusy(true);
    try {
      setRuntime(await managedServerStop());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLifecycleBusy(false);
    }
  };

  const runtimeBadge = managedRuntimeBadge(runtime, status.ready);

  const failed = progress?.phase === "error";
  const normalizedVoiceQuery = voiceQuery.trim().toLocaleLowerCase();
  const voiceResults = (catalog?.models ?? []).filter((choice) => {
    if (!normalizedVoiceQuery) return true;
    return [
      choice.label,
      choice.backend,
      choice.model,
      choice.note,
      choice.license ?? "",
      ...(choice.languages ?? []),
    ]
      .join(" ")
      .toLocaleLowerCase()
      .includes(normalizedVoiceQuery);
  });
  return (
    <div className="space-y-2 border-t border-border pt-3">
      <div className="flex items-start gap-2 text-xs">
        {status.ready ? (
          <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-foreground" />
        )}
        <span className="text-muted-foreground">
          {running ? (progress?.detail ?? status.sentence) : status.sentence}
        </span>
      </div>

      {!running && installed && runtimeBadge && (
        <div
          className="flex items-center gap-2 text-xs"
          data-testid="managed-server-runtime"
          aria-live="polite"
        >
          <span
            aria-hidden="true"
            className={cn(
              "h-1.5 w-1.5 shrink-0 rounded-full",
              runtimeBadge.tone === "ok"
                ? "bg-muted-foreground"
                : runtimeBadge.tone === "warn"
                  ? "animate-pulse bg-foreground motion-reduce:animate-none"
                  : "bg-muted-foreground/40",
            )}
          />
          <span
            className={cn(
              runtimeBadge.tone === "warn" ? "text-foreground" : "text-muted-foreground",
            )}
          >
            {t(runtimeBadge.key)}
          </span>
          {runtimeBadge.key === "apikeys_view.managed_server_starting" &&
            runtime?.boot?.starting &&
            runtime.boot.stage_label && (
              <span className="text-muted-foreground">
                {typeof runtime.boot.remaining_s === "number" &&
                runtime.boot.remaining_s > 0
                  ? `${runtime.boot.stage_label} · ${t(
                      "apikeys_view.managed_server_starting_eta",
                    ).replace(
                      "{0}",
                      String(
                        Math.max(
                          10,
                          Math.round(runtime.boot.remaining_s / 10) * 10,
                        ),
                      ),
                    )}`
                  : runtime.boot.stage_label}
              </span>
            )}
          {runtime && !runtime.reachable && !runtime.owned && (
            <Button
              size="sm"
              variant="secondary"
              onClick={startServer}
              disabled={lifecycleBusy}
              className="h-6 gap-1.5 px-2 text-xs"
            >
              {lifecycleBusy ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Play className="h-3 w-3" />
              )}
              {t("apikeys_view.managed_start_cta")}
            </Button>
          )}
          {runtime?.owned && (
            <Button
              size="sm"
              variant="ghost"
              onClick={stopServer}
              disabled={lifecycleBusy}
              className="h-6 gap-1.5 px-2 text-xs"
            >
              {lifecycleBusy ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Square className="h-3 w-3" />
              )}
              {t("apikeys_view.managed_stop_cta")}
            </Button>
          )}
        </div>
      )}

      {setupNote && (
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {setupNote}
        </p>
      )}

      {!running && catalog && (
        <div className="space-y-3" data-testid="managed-model-picker">
          <p className="text-xs text-muted-foreground" role="status">
            {t(descriptor.active ? "apikeys_view.managed_selected" : "apikeys_view.managed_not_selected")}
          </p>
          <div className="grid gap-2 sm:grid-cols-3">
            <label className="space-y-1.5">
              <span className="flex items-center gap-1.5 text-xs font-medium">
                <Mic className="h-3.5 w-3.5 text-muted-foreground" />
                {t("apikeys_view.managed_hearing_title")}
              </span>
              <span className="block text-xs">{catalog.hearing.label}</span>
              <span className="block text-xs leading-snug text-muted-foreground">
                {t("apikeys_view.managed_hearing_note")}
              </span>
            </label>

            <label className="space-y-1.5">
              <span className="flex items-center gap-1.5 text-xs font-medium">
                <Brain className="h-3.5 w-3.5 text-muted-foreground" />
                {t("apikeys_view.managed_thinking_title")}
              </span>
              <BrandedSelect
                ariaLabel={t("apikeys_view.managed_thinking_title")}
                value={selectedBrain}
                onValueChange={setSelectedBrain}
                disabled={setupBusy}
                className="h-8 px-2 text-xs"
                options={catalog.brain.models.map((choice) => ({
                  value: choice.id,
                  label: `${choice.label} · ~${choice.size_gb} GB${
                    choice.recommended
                      ? ` · ${t("apikeys_view.managed_brain_recommended")}`
                      : ""
                  }${
                    choice.fits
                      ? ""
                      : ` · ${t("apikeys_view.managed_brain_no_fit")}`
                  }`,
                  disabled: !choice.fits,
                }))}
              />
            </label>

            <label className="space-y-1.5">
              <span className="flex items-center gap-1.5 text-xs font-medium">
                <Volume2 className="h-3.5 w-3.5 text-muted-foreground" />
                {t("apikeys_view.managed_speaking_title")}
              </span>
              <BrandedSelect
                ariaLabel={t("apikeys_view.managed_speaking_title")}
                value={selectedVoice}
                onValueChange={setSelectedVoice}
                disabled={setupBusy}
                className="h-8 px-2 text-xs"
                options={catalog.models.map((choice) => ({
                  value: choice.id,
                  label: `${choice.label}${
                    choice.recommended
                      ? ` · ${t("apikeys_view.managed_brain_recommended")}`
                      : ""
                  }${
                    !choice.selectable
                      ? ` · ${t("apikeys_view.managed_voice_unavailable")}`
                      : choice.runtime_ready === false
                        ? ` · ${t("apikeys_view.managed_voice_install_required")}`
                        : ""
                  }`,
                  disabled: !choice.selectable,
                }))}
              />
            </label>
          </div>

          {installed && (
            <Button
              size="sm"
              onClick={() => void applySetup()}
              disabled={setupBusy || !selectedBrain || !selectedVoice}
              className="gap-2"
            >
              {setupBusy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Volume2 className="h-3.5 w-3.5" />
              )}
              {t("apikeys_view.managed_apply_test")}
            </Button>
          )}

          <details className="group text-xs">
              <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 font-medium text-muted-foreground transition-colors hover:text-foreground [&::-webkit-details-marker]:hidden">
                <ChevronDown
                  aria-hidden="true"
                  className="h-3 w-3 -rotate-90 transition-transform group-open:rotate-0 motion-reduce:transition-none"
                />
                {t("apikeys_view.managed_full_catalog")}
              </summary>
              <LibraryBrowser
                providerId="ollama"
                onPull={(model) => void applyCatalogModel(model, false)}
                onInstalledSelect={(model) => void applyCatalogModel(model, true)}
                disabled={setupBusy}
                pullingModel={libraryBusy}
                actionLabel={t("apikeys_view.managed_download_test")}
                installedActionLabel={t("apikeys_view.managed_use_test")}
              />
          </details>

          <details data-testid="managed-voice-catalog" className="group text-xs">
            <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 font-medium text-muted-foreground transition-colors hover:text-foreground [&::-webkit-details-marker]:hidden">
              <ChevronDown
                aria-hidden="true"
                className="h-3 w-3 -rotate-90 transition-transform group-open:rotate-0 motion-reduce:transition-none"
              />
              {t("apikeys_view.managed_voice_catalog_title")}
            </summary>
            <div className="mt-2 space-y-2">
              <label className="relative block">
                <Search
                  aria-hidden="true"
                  className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground"
                />
                <input
                  type="search"
                  value={voiceQuery}
                  onChange={(event) => setVoiceQuery(event.target.value)}
                  placeholder={t("apikeys_view.managed_voice_catalog_search")}
                  aria-label={t("apikeys_view.managed_voice_catalog_search")}
                  className="h-8 w-full rounded-md border border-border bg-background pl-8 pr-2 text-xs"
                />
              </label>

              {voiceResults.length === 0 ? (
                <p className="px-1 py-2 text-xs text-muted-foreground">
                  {t("apikeys_view.managed_voice_catalog_empty")}
                </p>
              ) : (
                <div className="max-h-80 space-y-1.5 overflow-y-auto pr-1">
                  {voiceResults.map((choice) => (
                    <div
                      key={choice.id}
                      data-testid={`managed-voice-row-${choice.id}`}
                      className={cn(
                        "flex items-start justify-between gap-3 rounded-md border px-2.5 py-2",
                        choice.id === selectedVoice
                          ? "border-border-strong bg-primary/[0.05]"
                          : "border-border bg-background",
                      )}
                    >
                      <div className="min-w-0 space-y-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="text-xs font-medium">{choice.label}</span>
                          {choice.frontier && (
                            <span className="rounded-full bg-secondary px-1.5 py-px text-xs font-semibold text-foreground-strong">
                              {t("apikeys_view.managed_voice_frontier")}
                            </span>
                          )}
                          {choice.streaming && (
                            <span className="rounded-full border border-border px-1.5 py-px text-xs text-muted-foreground">
                              {t("apikeys_view.managed_voice_streaming")}
                            </span>
                          )}
                          <span
                            className={cn(
                              "rounded-full border px-1.5 py-px text-xs",
                              choice.selectable
                                ? "border-muted-foreground/30 bg-muted-foreground/10 text-muted-foreground"
                                : "bg-secondary text-foreground",
                            )}
                          >
                            {t(
                              choice.selectable
                                ? "apikeys_view.managed_voice_compatible"
                                : "apikeys_view.managed_voice_integration_pending",
                            )}
                          </span>
                        </div>
                        <p className="break-all font-mono text-xs text-muted-foreground">
                          {choice.model}
                        </p>
                        <p className="text-xs leading-snug text-muted-foreground">
                          {choice.note}
                        </p>
                        <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
                          {(choice.languages ?? []).slice(0, 12).map((language) => (
                            <span key={language} className="rounded bg-muted px-1 py-px ">
                              {language}
                            </span>
                          ))}
                          {(choice.languages?.length ?? 0) > 12 && (
                            <span>+{(choice.languages?.length ?? 0) - 12}</span>
                          )}
                          {choice.release_date && <span>· {choice.release_date}</span>}
                          {choice.license && <span>· {choice.license}</span>}
                          {(choice.size_gb ?? 0) > 0 && <span>· ~{choice.size_gb} GB</span>}
                          {choice.source_url && (
                            <a
                              href={choice.source_url}
                              target="_blank"
                              rel="noreferrer"
                              className="font-medium text-foreground-strong hover:underline"
                            >
                              {t("apikeys_view.managed_voice_source")}
                            </a>
                          )}
                        </div>
                      </div>
                      {choice.selectable && (
                        <Button
                          size="sm"
                          variant={choice.id === selectedVoice ? "secondary" : "outline"}
                          disabled={setupBusy || !selectedBrain}
                          onClick={() => void applyVoiceChoice(choice)}
                          className="h-7 shrink-0 gap-1 px-2 text-xs"
                        >
                          {setupBusy && choice.id === selectedVoice ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Volume2 className="h-3 w-3" />
                          )}
                          {t(
                            choice.runtime_ready === false
                              ? "apikeys_view.managed_voice_install_test"
                              : "apikeys_view.managed_use_test",
                          )}
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </details>
        </div>
      )}

      {running && (
        <div className="space-y-1">
          <div className="h-1.5 w-full overflow-hidden rounded bg-muted">
            <div
              className="h-full rounded bg-secondary transition-all"
              style={{ width: `${Math.max(2, progress?.percent ?? 0)}%` }}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            {t("apikeys_view.managed_hint")}
          </p>
        </div>
      )}

      {!status.ready && !running && !preflight && (
        <Button
          size="sm"
          variant="secondary"
          onClick={check}
          disabled={checking}
          className="gap-2"
        >
          {checking ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Download className="h-3.5 w-3.5" />
          )}
          {failed
            ? t("apikeys_view.managed_retry")
            : t("apikeys_view.managed_check_cta")}
        </Button>
      )}

      {!status.ready && !running && preflight && !preflight.ok && !preflight.brain_fixable && (
        <div className="space-y-2 text-xs">
          <p className="text-foreground">{preflight.blocker}</p>
          <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
            {preflight.actions.map((action) => (
              <li key={action}>{action}</li>
            ))}
          </ul>
        </div>
      )}

      {!status.ready &&
        !running &&
        preflight &&
        (preflight.ok || preflight.brain_fixable) &&
        preflight.tier && (
          <div className="space-y-2 text-xs">
            <div className="space-y-0.5 text-muted-foreground">
              <p>
                {preflight.tier.label} · {t("apikeys_view.managed_download_size")}{" "}
                ~{preflight.tier.download_gb} GB ·{" "}
                {t("apikeys_view.managed_latency")}{" "}
                {preflight.tier.expected_latency}
              </p>
              <p>{preflight.stack_sentence}</p>
              {preflight.brain && <p>{preflight.brain.note}</p>}
              {/* Blocked brain, but the install fixes it itself: say so
                  honestly BEFORE the click — Ollama plus the brain model are
                  extra downloads the tier size above does not include. */}
              {!preflight.ok && preflight.brain_fixable && (
                <p className="text-foreground">
                  {t("apikeys_view.managed_brain_setup_note")}
                </p>
              )}
            </div>
            <Button size="sm" onClick={startInstall} className="gap-2">
              <Download className="h-3.5 w-3.5" />
              {t("apikeys_view.managed_install_cta")}
            </Button>
          </div>
        )}

      {anythingOnDisk && !running && (
        <Button
          size="sm"
          variant="ghost"
          onClick={remove}
          className={cn(
            "gap-2 text-muted-foreground hover:text-destructive",
            confirmRemove && "text-destructive",
          )}
        >
          <XCircle className="h-3.5 w-3.5" />
          {confirmRemove
            ? t("apikeys_view.managed_uninstall_confirm")
            : t("apikeys_view.managed_uninstall")}
        </Button>
      )}

      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
