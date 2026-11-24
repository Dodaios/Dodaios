import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, Check, ChevronDown, Download, Loader2, Play, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { modelLibraryTags, modelPullStatus, ollamaRuntime, ollamaRuntimeInstall, ollamaRuntimeStart, startModelPull, type OllamaRuntimeInstallProgress, type OllamaRuntimeStatus, pullableModels, searchModelLibrary, type LibraryModel, type LibraryTag, type ModelPullProgress, type PullableModel, type PullableRole, type PullableModels } from "@/hooks/useProviders";
import { cn } from "@/lib/utils";
import { useT } from "@/i18n";

/**
 * Install or start the Ollama runtime itself — the last terminal step on the
 * local-model path. Invisible while Ollama runs (nothing to do); when it is
 * stopped it offers Start, when it is absent it offers a confirmed Install
 * (official ollama.com artifacts only, backend-authored status sentences
 * rendered verbatim). Mounted on pull-capable cards and inside the managed
 * realtime card's blocked-brain state. The Local models section mounts it
 * with `alwaysVisible`, where a healthy server shows one green running line
 * instead of disappearing — a dedicated Server tab must never look empty.
 */
export function OllamaRuntimePanel({
  providerId,
  onChanged,
  alwaysVisible = false,
}: {
  /** The pull-capable card whose runtime routes this panel drives. */
  providerId: string;
  onChanged: () => void;
  /** Render the healthy state too (a green running line) instead of nothing. */
  alwaysVisible?: boolean;
}) {
  const t = useT();
  const [status, setStatus] = useState<OllamaRuntimeStatus | null>(null);
  const [progress, setProgress] = useState<OllamaRuntimeInstallProgress | null>(
    null,
  );
  const [confirmInstall, setConfirmInstall] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const installing = Boolean(progress?.running);

  const refresh = useCallback(async () => {
    try {
      const next = await ollamaRuntime(providerId);
      // A mocked/older backend may answer with a partial body — treat any
      // missing half as "no data" instead of crashing the whole card.
      if (!next.status || !next.install) return null;
      setStatus(next.status);
      setProgress(next.install);
      return next;
    } catch {
      return null;
    }
  }, [providerId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!installing) return;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      const next = await refresh();
      if (cancelled || next === null) return;
      if (!next.install.running) {
        window.clearInterval(timer);
        if (next.install.phase === "error") {
          setError(next.install.error || t("apikeys_view.install_failed_fallback"));
        }
        onChanged();
      }
    }, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [installing, refresh, onChanged]);

  const install = async () => {
    if (!confirmInstall) {
      setConfirmInstall(true);
      return;
    }
    setConfirmInstall(false);
    setError(null);
    try {
      const first = await ollamaRuntimeInstall(providerId);
      setProgress(first);
      if (!first.running && first.phase === "error" && first.error) {
        setError(first.error);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const start = async () => {
    setError(null);
    setBusy(true);
    try {
      const next = await ollamaRuntimeStart(providerId);
      if (next) setStatus(next);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (status === null) return null;
  if (status.running && !installing) {
    if (!alwaysVisible) return null; // healthy — stay out of the way
    return (
      <div
        className="flex items-start gap-2 text-xs"
        data-testid="ollama-runtime-panel"
        data-state="running"
      >
        <span
          aria-hidden="true"
          className="mt-1 h-2 w-2 shrink-0 rounded-full bg-muted-foreground"
        />
        <span className="text-muted-foreground">
          {status.detail ||
            t("apikeys_view.ollama_running_line").replace("{0}", status.version || "")}
        </span>
      </div>
    );
  }

  return (
    <div
      className="space-y-2 border-t border-border pt-3"
      data-testid="ollama-runtime-panel"
    >
      <div className="flex items-start gap-2 text-xs">
        <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-foreground" />
        <span className="text-muted-foreground">
          {installing ? (progress?.detail ?? status.detail) : status.detail}
        </span>
      </div>

      {installing && (
        <div className="h-1.5 w-full overflow-hidden rounded bg-muted">
          <div
            className="h-full rounded bg-secondary transition-all"
            style={{ width: `${Math.max(2, progress?.percent ?? 0)}%` }}
          />
        </div>
      )}

      {!installing && !status.installed && (
        <div className="space-y-1">
          <Button size="sm" onClick={install} className="gap-2">
            <Download className="h-3.5 w-3.5" />
            {confirmInstall
              ? t("apikeys_view.ollama_install_confirm")
              : t("apikeys_view.ollama_install_cta")}
          </Button>
          <p className="text-xs text-muted-foreground">
            {t("apikeys_view.ollama_install_hint")}
          </p>
        </div>
      )}

      {!installing && status.installed && !status.running && (
        <Button
          size="sm"
          variant="secondary"
          onClick={start}
          disabled={busy}
          className="gap-2"
        >
          {busy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Play className="h-3.5 w-3.5" />
          )}
          {t("apikeys_view.ollama_start_cta")}
        </Button>
      )}

      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

/**
 * Browse the provider's WHOLE public library, not just the curated shortlist.
 *
 * The shortlist answers "which model should I get?" for someone who has no
 * opinion. Someone who does had exactly one way through before this: type an
 * exact tag into a blind text field and hope. That meant leaving the app for a
 * browser, and it silently punished the common mistake of pulling a bare name
 * (`qwen3.5` is 6.6 GB; `qwen3.5:122b` is not).
 *
 * So the same field now searches. Results carry the catalog's own blurb and
 * badges, and opening one lists every published version with its real download
 * size and the SAME fit verdict the shortlist uses. Nothing here is required:
 * the field still pulls whatever is typed, so a machine that cannot reach the
 * public catalog keeps the exact-name path it always had.
 */
export function LibraryBrowser({
  providerId,
  onPull,
  onInstalledSelect,
  disabled,
  pullingModel,
  actionLabel,
  installedActionLabel,
}: {
  providerId: string;
  onPull: (model: string) => void;
  onInstalledSelect?: (model: string) => void;
  /** The local server is unreachable — nothing can be downloaded into it. */
  disabled: boolean;
  /** Id of the download in flight, so its row shows the spinner. */
  pullingModel: string | null;
  actionLabel?: string;
  installedActionLabel?: string;
}) {
  const t = useT();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<LibraryModel[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [libraryError, setLibraryError] = useState<string | null>(null);
  const [openModel, setOpenModel] = useState<string | null>(null);
  const [tags, setTags] = useState<Record<string, LibraryTag[]>>({});
  const [tagsError, setTagsError] = useState<string | null>(null);
  const [loadingTags, setLoadingTags] = useState(false);

  // Nothing is fetched until the user asks for it. The panel renders inside a
  // provider LIST, and a search-on-mount would hit the public catalog once per
  // card on every render of the settings view.
  const [browsing, setBrowsing] = useState(false);

  const runSearch = useCallback(
    async (q: string) => {
      setSearching(true);
      try {
        const answer = await searchModelLibrary(providerId, q);
        setResults(answer.models);
        setLibraryError(answer.error);
      } catch (err) {
        setResults([]);
        setLibraryError(err instanceof Error ? err.message : String(err));
      } finally {
        setSearching(false);
      }
    },
    [providerId],
  );

  // Debounced: a search per keystroke would hammer the catalog and make the
  // list flicker between partial-word answers.
  useEffect(() => {
    if (!browsing) return;
    const timer = window.setTimeout(() => void runSearch(query.trim()), 350);
    return () => window.clearTimeout(timer);
  }, [browsing, query, runSearch]);

  const toggleModel = async (name: string) => {
    if (openModel === name) {
      setOpenModel(null);
      return;
    }
    setOpenModel(name);
    setTagsError(null);
    if (tags[name]) return;
    setLoadingTags(true);
    try {
      const answer = await modelLibraryTags(providerId, name);
      if (answer.error) setTagsError(answer.error);
      setTags((prev) => ({ ...prev, [name]: answer.tags }));
    } catch (err) {
      setTagsError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingTags(false);
    }
  };

  return (
    <div className="space-y-2 border-t border-border pt-2" data-testid="model-library">
      {/* The first version of this shipped as a bare input with a changed
          placeholder, in the exact spot the old blind text field had occupied.
          It worked and nobody could see it: a feature that looks identical to
          what it replaced has not been delivered. Hence the heading — the
          panel has to SAY that the whole catalog is searchable here. */}
      <p className="flex items-center gap-1.5 text-xs font-medium">
        <Search className="h-3.5 w-3.5 text-muted-foreground" />
        {t("apikeys_model_pull.library_title")}
      </p>
      <div className="flex items-center gap-2">
        <div className="relative w-full">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            value={query}
            onFocus={() => setBrowsing(true)}
            onChange={(e) => {
              setQuery(e.target.value);
              setBrowsing(true);
            }}
            placeholder={t("apikeys_model_pull.custom_placeholder")}
            className="h-8 w-full rounded-md border border-border bg-background pl-7 pr-2 text-xs"
          />
        </div>
        {/* The exact-name path the panel has always had: whatever is typed can
            be pulled directly, whether or not the catalog was reachable. */}
        <Button
          size="sm"
          variant="secondary"
          disabled={disabled || pullingModel !== null || !query.trim()}
          onClick={() => onPull(query)}
        >
          {actionLabel ?? t("apikeys_model_pull.download")}
        </Button>
      </div>

      {browsing && (
        <div className="space-y-1.5">
          {searching && !results && (
            <p className="text-xs text-muted-foreground">
              {t("apikeys_model_pull.library_searching")}
            </p>
          )}
          {/* An unreachable catalog is a note, never a blocker — the field
              above still downloads by exact name. */}
          {libraryError && (
            <p className="text-xs text-foreground">{libraryError}</p>
          )}
          {results && results.length === 0 && !libraryError && (
            <p className="text-xs text-muted-foreground">
              {t("apikeys_model_pull.library_no_results")}
            </p>
          )}

          {(results ?? []).map((model) => (
            <div
              key={model.name}
              data-testid={`library-row-${model.name}`}
              className="rounded border border-border bg-background"
            >
              <button
                type="button"
                className="flex w-full items-start justify-between gap-2 px-2 py-1.5 text-left"
                onClick={() => void toggleModel(model.name)}
              >
                <div className="min-w-0">
                  <p className="truncate text-xs font-medium">
                    {model.name}
                    {model.installed && (
                      <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                        {t("apikeys_model_pull.installed")}
                      </span>
                    )}
                  </p>
                  {model.description && (
                    <p className="text-xs leading-snug text-muted-foreground">
                      {model.description}
                    </p>
                  )}
                  <div className="mt-0.5 flex flex-wrap gap-1">
                    {model.capabilities.map((cap) => (
                      <span
                        key={cap}
                        className="rounded bg-secondary px-1 py-px text-xs font-medium text-foreground-strong"
                      >
                        {cap}
                      </span>
                    ))}
                    {model.sizes.slice(0, 6).map((size) => (
                      <span
                        key={size}
                        className="rounded bg-muted px-1 py-px text-xs font-medium text-muted-foreground"
                      >
                        {size}
                      </span>
                    ))}
                  </div>
                </div>
                <ChevronDown
                  className={cn(
                    "mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
                    openModel === model.name && "rotate-180",
                  )}
                />
              </button>

              {openModel === model.name && (
                // A popular family publishes well over a hundred tags
                // (qwen2.5: 133). Un-capped, one opened model would push the
                // whole settings page down by several screens.
                <div className="max-h-56 space-y-1 overflow-y-auto border-t border-border px-2 py-1.5">
                  {loadingTags && !tags[model.name] && (
                    <p className="text-xs text-muted-foreground">
                      {t("apikeys_model_pull.library_loading_versions")}
                    </p>
                  )}
                  {tagsError && (
                    <p className="text-xs text-foreground">{tagsError}</p>
                  )}
                  {(tags[model.name] ?? []).map((tag) => (
                    <div
                      key={tag.id}
                      data-testid={`library-tag-${tag.id}`}
                      className="flex items-center justify-between gap-2"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-xs">
                          <span className="font-mono">{tag.id}</span>{" "}
                          <span className="text-muted-foreground">
                            {tag.size_gb
                              ? t("apikeys_model_pull.size").replace(
                                  "{0}",
                                  String(tag.size_gb),
                                )
                              : t("apikeys_model_pull.library_size_unknown")}
                            {tag.context
                              ? ` · ${t("apikeys_model_pull.library_context").replace("{0}", tag.context)}`
                              : ""}
                          </span>
                        </p>
                        {tag.fit === "tight" && tag.fit_note && (
                          <p className="text-xs leading-snug text-foreground">
                            {tag.fit_note}
                          </p>
                        )}
                      </div>
                      {/* A hosted tag has no weights to fetch. Offering
                          "Download" for it would fail at the server. */}
                      {tag.cloud ? (
                        <span className="shrink-0 text-xs text-muted-foreground">
                          {t("apikeys_model_pull.library_hosted")}
                        </span>
                      ) : tag.installed && onInstalledSelect ? (
                        <Button
                          size="sm"
                          variant="secondary"
                          className="h-6 shrink-0 gap-1 px-2 text-xs"
                          disabled={disabled || pullingModel !== null}
                          onClick={() => onInstalledSelect(tag.id)}
                        >
                          {pullingModel === tag.id ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Check className="h-3 w-3" />
                          )}
                          {installedActionLabel ?? t("apikeys_model_pull.installed")}
                        </Button>
                      ) : tag.installed ? (
                        <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
                          <Check className="h-3 w-3" />
                          {t("apikeys_model_pull.installed")}
                        </span>
                      ) : (
                        <Button
                          size="sm"
                          variant="secondary"
                          className="h-6 shrink-0 gap-1 px-2 text-xs"
                          disabled={disabled || pullingModel !== null}
                          onClick={() => onPull(tag.id)}
                        >
                          {pullingModel === tag.id ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Download className="h-3 w-3" />
                          )}
                          {actionLabel ?? t("apikeys_model_pull.download")}
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * The download half of a keyless local brain card: which models this machine
 * could run, which it already has, and the one button that fetches one.
 *
 * Without it a keyless install dead-ended at "run: ollama pull <model>" — a
 * terminal instruction in an app that has no terminal, and the exact point
 * where §3's "recoverable in-app" contract broke. Nothing is inferred client
 * side: installed state, fit verdict and progress all come from the server,
 * because only it can see the user's inventory and memory. The fit verdict is
 * advisory — a GPU runs models the RAM rule calls tight, so it never disables
 * the button.
 */
export function LocalModelDownloadPanel({
  descriptor,
  onChanged,
}: {
  /**
   * Only the two fields the panel actually uses. Widened from
   * `ProviderDescriptor` so the Subagents tab — whose rows come from a
   * different endpoint with a different shape — can render the very same panel
   * instead of dead-ending a local-only user at an empty model dropdown.
   */
  descriptor: { id: string; supports_model_pull?: boolean };
  onChanged: () => void;
}) {
  const t = useT();
  const [catalog, setCatalog] = useState<PullableModels | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<ModelPullProgress | null>(null);
  const running = progress?.state === "running";

  // Hooks run before the capability check below, so the fetch itself is gated:
  // a cloud card that mounted this panel would otherwise fire a request the
  // route answers with 400 on every render of the provider list.
  const pullable = Boolean(descriptor.supports_model_pull);
  const load = useMemo(
    () => async () => {
      if (!pullable) return;
      try {
        setCatalog(await pullableModels(descriptor.id));
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [descriptor.id, pullable],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // Poll only while a pull is in flight. A finished download refreshes both the
  // shortlist (so the row flips to "installed") and the provider list (so the
  // model picker sees the new model without a restart).
  useEffect(() => {
    if (!running || !progress) return;
    let cancelled = false;
    const model = progress.model;
    const timer = window.setInterval(async () => {
      try {
        const next = await modelPullStatus(descriptor.id, model);
        if (cancelled) return;
        setProgress(next);
        if (next.state === "done" || next.state === "error") {
          window.clearInterval(timer);
          void load();
          onChanged();
        }
      } catch (err) {
        if (cancelled) return;
        window.clearInterval(timer);
        setError(err instanceof Error ? err.message : String(err));
        setProgress(null);
      }
    }, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [running, progress, descriptor.id, load, onChanged]);

  if (!pullable) return null;

  const pull = async (model: string) => {
    const name = model.trim();
    if (!name) return;
    setError(null);
    try {
      const started = await startModelPull(descriptor.id, name);
      setProgress(started);
      if (started.state === "done") {
        void load();
        onChanged();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const percent = progress?.percent ?? 0;
  const rows: PullableModel[] = catalog?.models ?? [];
  // Roles come from the backend, in its order. A payload without them (an older
  // server) collapses into one unlabelled group, which is exactly how this
  // panel looked before roles existed — no empty headings, no crash.
  const roles: PullableRole[] = catalog?.roles ?? [];
  const groups: { role: PullableRole | null; rows: PullableModel[] }[] = roles.length
    ? roles
        .map((role) => ({
          role,
          rows: rows.filter((r) => (r.role ?? "chat") === role),
        }))
        .filter((g) => g.rows.length > 0)
    : [{ role: null, rows }];
  // What the fit verdicts were judged against, in one short phrase. Naming the
  // GPU matters: "18 GB is tight" is confusing on a box with 64 GB of RAM until
  // you know the number being compared is the graphics card's.
  const hardwareNote = catalog
    ? (catalog.accelerator_gb ?? 0) > 0
      ? t("apikeys_model_pull.hardware_gpu").replace(
          "{0}",
          String(Math.round(catalog.accelerator_gb ?? 0)),
        )
      : catalog.memory_gb
        ? t("apikeys_model_pull.memory").replace("{0}", String(catalog.memory_gb))
        : ""
    : "";

  return (
    <div
      data-testid={`provider-model-pull-${descriptor.id}`}
      className="space-y-2 border-t border-border pt-3"
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium">{t("apikeys_model_pull.title")}</p>
        {hardwareNote ? (
          <span
            data-testid="model-pull-hardware"
            className="text-xs text-muted-foreground"
          >
            {hardwareNote}
          </span>
        ) : null}
      </div>

      {catalog && !catalog.server_reachable && (
        <p className="text-xs text-foreground">{catalog.message}</p>
      )}

      {groups.map((group) => (
        <div key={group.role ?? "all"} className="space-y-1.5">
          {group.role && (
            <p className="pt-1 text-xs font-semibold text-muted-foreground">
              {t(`apikeys_model_pull.role_${group.role}`)}
            </p>
          )}
          {group.rows.map((row) => (
          <div
            key={row.id}
            data-testid={`model-pull-row-${row.id}`}
            data-recommended={row.recommended ? "true" : "false"}
            className={cn(
              "flex items-start justify-between gap-2 rounded border bg-background px-2 py-1.5",
              row.recommended
                ? "border-border-strong bg-primary/[0.04]"
                : "border-border/50",
            )}
          >
            <div className="min-w-0">
              <p className="truncate text-xs font-medium">
                {row.label}{" "}
                <span className="font-normal text-muted-foreground">
                  {t("apikeys_model_pull.size").replace(
                    "{0}",
                    String(row.size_gb),
                  )}
                </span>
                {row.recommended && (
                  <span className="ml-1.5 whitespace-nowrap rounded-full bg-secondary px-1.5 py-px text-xs font-semibold text-foreground-strong">
                    {t("apikeys_model_pull.best_for_machine")}
                  </span>
                )}
              </p>
              <p className="text-xs leading-snug text-muted-foreground">
                {row.purpose}
              </p>
              {/* The honest half of a recommendation: the comfortable note
                  explains why THIS one was picked, the tight note explains what
                  a bigger one would cost. Both are the server's wording. */}
              {(row.fit === "tight" || row.recommended) && (
                <p
                  className={cn(
                    "text-xs leading-snug",
                    row.fit === "tight" ? "text-foreground" : "text-muted-foreground/80",
                  )}
                >
                  {row.fit_note}
                </p>
              )}
            </div>
            {row.installed ? (
              <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
                <Check className="h-3.5 w-3.5" />
                {t("apikeys_model_pull.installed")}
              </span>
            ) : (
              <Button
                size="sm"
                variant={row.recommended ? "default" : "secondary"}
                className="shrink-0 gap-1.5"
                disabled={running || !catalog?.server_reachable}
                onClick={() => void pull(row.id)}
              >
                {running && progress?.model === row.id ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Download className="h-3.5 w-3.5" />
                )}
                {t("apikeys_model_pull.download")}
              </Button>
            )}
          </div>
          ))}
        </div>
      ))}

      {/* Any name the library knows — the shortlist is a starting point, not a
          gate, and a user who wants a specific model should not have to leave
          the app for it. */}
      <LibraryBrowser
        providerId={descriptor.id}
        onPull={(model) => void pull(model)}
        disabled={running || !catalog?.server_reachable}
        pullingModel={running ? (progress?.model ?? null) : null}
      />

      {progress && progress.state !== "idle" && (
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">
            {progress.model}: {progress.message}
          </p>
          {running && (
            <div className="h-1 w-full overflow-hidden rounded bg-border">
              <div
                className="h-full bg-secondary transition-all"
                style={{ width: `${percent}%` }}
              />
            </div>
          )}
        </div>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
