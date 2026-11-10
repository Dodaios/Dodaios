import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, ExternalLink, Github, MoreHorizontal, RefreshCw, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ActionMenu, IconButton, type MenuAction } from "@/components/extensions/primitives";
import {
  GithubSignInDialog,
  PublisherChip,
  usePublishIdentity,
} from "@/components/marketplace/PublishIdentity";
import { PublishStudio } from "@/components/marketplace/PublishStudio";
import { isCreateCancelled, useCreateAgentDialog } from "@/components/society/create/createAgentStore";
import { fill, useLocaleChunk, useT } from "@/i18n";
import { readFileText } from "@/lib/agentShare";
import { MARKETPLACE_WEB_URL } from "@/lib/branding";
import { openExternalUrl } from "@/lib/openExternal";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { INDEX_KEY, useInstallEntry, useRefreshIndex, useRemoveEntry, useStoreIndex } from "@/views/marketplace/api";
import { EntryPage } from "@/views/marketplace/EntryPage";
import {
  entriesOf,
  entryKey,
  filterCounts,
  HOME_SECTION,
  passesFilter,
  searchEntries,
  type Entry,
  type InstallResultWire,
  type StoreFilter,
} from "@/views/marketplace/model";
import { StoreHome } from "@/views/marketplace/StoreHome";

// ---------------------------------------------------------------------------
// The marketplace, as a section of its own.
//
// Two pages share this frame: the store (search, the kind switch, every
// published entry as a row) and one entry's page. The store stays mounted
// behind an open entry, so going back lands on the same search at the same
// scroll position.
//
// Everything published here is third-party content that passed automated
// checks and no human review. That is why nothing installs from a row: the
// install button lives on the entry's page, next to what the entry reaches and
// the files it is made of.
// ---------------------------------------------------------------------------

type Translate = (key: string) => string;

/** What the store just did, said once at the foot of the page. */
type Landing =
  | { type: "installed"; result: InstallResultWire }
  | { type: "removed"; title: string };

export function MarketplaceView() {
  const t = useT();
  // Section-only strings ride in a lazy chunk (bundle budget); the store waits
  // for it so no row ever paints a raw key.
  const localeReady = useLocaleChunk("marketplace");
  const queryClient = useQueryClient();
  const setActiveSection = useEventStore((s) => s.setActiveSection);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<StoreFilter>("all");
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [landing, setLanding] = useState<Landing | null>(null);
  const [studioOpen, setStudioOpen] = useState(false);
  const [signInOpen, setSignInOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const identity = usePublishIdentity();
  const login = identity.data?.signed_in ? (identity.data.login ?? null) : null;
  const publishEnabled = identity.data?.enabled !== false;

  const index = useStoreIndex();
  const refresh = useRefreshIndex();
  const install = useInstallEntry((result) => setLanding({ type: "installed", result }));
  const remove = useRemoveEntry((entry) => setLanding({ type: "removed", title: entry.title }));

  // An exported template from somebody else: previewed in the New-agent
  // dialog, and created only once the person confirms it there.
  const importAgent = useMutation({
    mutationFn: async (file: File): Promise<InstallResultWire | null> => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(await readFileText(file));
      } catch {
        throw new Error(fill(t("marketplace.import_failed"), { error: file.name }));
      }
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error(fill(t("marketplace.import_failed"), { error: file.name }));
      }
      try {
        const agent = await useCreateAgentDialog.getState().request({ template: parsed as Record<string, unknown> });
        return { ok: true, kind: "agent", id: agent.agentId, title: agent.name, ready: true };
      } catch (err) {
        if (isCreateCancelled(err)) return null;
        throw new Error(fill(t("marketplace.import_failed"), { error: (err as Error).message }));
      }
    },
    onSuccess: (result) => {
      if (!result) return;
      setLanding({ type: "installed", result });
      queryClient.invalidateQueries({ queryKey: ["society", "roster"] });
      queryClient.invalidateQueries({ queryKey: INDEX_KEY });
    },
  });

  const entries = useMemo(() => entriesOf(index.data), [index.data]);
  const searched = useMemo(() => searchEntries(entries, query), [entries, query]);
  const counts = useMemo(() => filterCounts(searched, login), [searched, login]);
  const visible = useMemo(
    () => searched.filter((entry) => passesFilter(entry, filter, login)),
    [searched, filter, login],
  );
  // Looked up fresh on every index answer, so an install flips the open page
  // to "Installed" without anybody reopening it.
  const openEntry = useMemo(
    () => (openKey ? (entries.find((entry) => entryKey(entry) === openKey) ?? null) : null),
    [entries, openKey],
  );

  const openDetail = (entry: Entry) => {
    // An error from another entry must not follow the reader here; a running
    // request keeps its state so its spinner stays honest.
    if (!install.isPending) install.reset();
    if (!remove.isPending) remove.reset();
    setLanding(null);
    setOpenKey(entryKey(entry));
  };

  const goBack = () => {
    const key = openKey;
    setOpenKey(null);
    // Focus returns to the row that was opened.
    requestAnimationFrame(() => {
      if (!key) return;
      const rows = document.querySelectorAll<HTMLElement>("[data-entry-key]");
      Array.from(rows).find((row) => row.dataset.entryKey === key)?.focus();
    });
  };

  // "/" jumps into the search, the way every store with a search does —
  // unless the person is typing somewhere, or something lies above the store.
  const coveredRef = useRef(false);
  coveredRef.current = openEntry !== null || studioOpen || signInOpen;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return;
      if (coveredRef.current) return;
      const target = event.target;
      if (target instanceof Element && target.closest("input, textarea, [contenteditable='true']")) return;
      event.preventDefault();
      searchRef.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const menu: MenuAction[] = [
    {
      id: "refresh",
      label: t("marketplace.refresh"),
      icon: <RefreshCw className="h-3.5 w-3.5" />,
      onSelect: () => refresh.mutate(),
      disabled: refresh.isPending,
    },
    {
      id: "web",
      label: t("marketplace.open_web"),
      icon: <ExternalLink className="h-3.5 w-3.5" />,
      onSelect: () => openExternalUrl(MARKETPLACE_WEB_URL),
    },
  ];
  if (publishEnabled && identity.data && !identity.data.signed_in && localeReady) {
    menu.push({
      id: "sign-in",
      label: t("marketplace.identity_sign_in"),
      icon: <Github className="h-3.5 w-3.5" />,
      onSelect: () => setSignInOpen(true),
      separatorAbove: true,
    });
  }

  const actionError = (mutation: { error: unknown; variables: Entry | undefined }) =>
    mutation.error && openEntry && mutation.variables && entryKey(mutation.variables) === entryKey(openEntry)
      ? (mutation.error as Error).message
      : null;

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <div className="flex h-12 shrink-0 items-center gap-2 px-4">
        <div className="ml-auto flex items-center gap-1.5">
          <ActionMenu
            label={t("marketplace.more_actions")}
            actions={menu}
            trigger={({ toggle }) => (
              <IconButton label={t("marketplace.more_actions")} onClick={toggle} busy={refresh.isPending}>
                <MoreHorizontal className="h-4 w-4" />
              </IconButton>
            )}
          />
          {login !== null && (
            <PublisherChip
              onSignIn={() => setSignInOpen(true)}
              onMine={() => {
                setOpenKey(null);
                setFilter("mine");
                setQuery("");
              }}
            />
          )}
          {publishEnabled && (
            <Button size="sm" onClick={() => setStudioOpen(true)} data-testid="marketplace-publish">
              {t("marketplace.publish_cta")}
            </Button>
          )}
        </div>
      </div>

      <div className={cn("min-h-0 flex-1 flex-col", openEntry ? "hidden" : "flex")}>
        <StoreHome
          t={t}
          loading={index.isLoading || (!index.error && !localeReady)}
          loadError={index.error && localeReady ? (index.error as Error).message : null}
          status={index.data?.status}
          searched={searched}
          visible={visible}
          counts={counts}
          empty={entries.length === 0}
          query={query}
          onQuery={setQuery}
          filter={filter}
          onFilter={setFilter}
          signedIn={login !== null}
          publishEnabled={publishEnabled}
          searchRef={searchRef}
          onOpen={openDetail}
          onPublish={() => setStudioOpen(true)}
          onImport={(file) => importAgent.mutate(file)}
          importing={importAgent.isPending}
          importError={importAgent.error ? (importAgent.error as Error).message : null}
          onBrowseBuiltIn={() => setActiveSection("plugins")}
          onRetry={() => (index.error ? index.refetch() : refresh.mutate())}
          retrying={refresh.isPending || index.isRefetching}
          refreshError={refresh.error ? (refresh.error as Error).message : null}
        />
      </div>

      {openEntry && (
        <EntryPage
          key={entryKey(openEntry)}
          entry={openEntry}
          t={t}
          onBack={goBack}
          onInstall={() => install.mutate(openEntry)}
          onRemove={() => remove.mutate(openEntry)}
          onOpenHome={() => setActiveSection(HOME_SECTION[openEntry.kind])}
          installing={install.isPending && install.variables?.name === openEntry.name}
          removing={remove.isPending && remove.variables?.name === openEntry.name}
          actionError={actionError(install) ?? actionError(remove)}
        />
      )}

      {landing && <LandingNote landing={landing} onClose={() => setLanding(null)} t={t} />}

      {studioOpen && <PublishStudio onClose={() => setStudioOpen(false)} />}
      {signInOpen && <GithubSignInDialog onClose={() => setSignInOpen(false)} />}
    </div>
  );
}

/**
 * Where the thing landed — and the way to it.
 *
 * An install that ends in a tick leaves the person holding something they
 * cannot find. This says what arrived, whether it is usable yet, and jumps to
 * the section that now holds it.
 */
function LandingNote({
  landing,
  onClose,
  t,
}: {
  landing: Landing;
  onClose: () => void;
  t: Translate;
}) {
  const setActiveSection = useEventStore((s) => s.setActiveSection);
  const result = landing.type === "installed" ? landing.result : null;
  const ready = result ? result.ready !== false : true;
  // A plugin always lands unconnected — that is its next step, not a fault.
  // Only a named problem (or a skill that is not usable) earns the warning.
  const warn = result ? Boolean(result.problem) || (!ready && result.kind !== "plugin") : false;
  const title = result
    ? fill(t("marketplace.landed_title"), { title: result.title ?? result.id ?? "" })
    : fill(t("marketplace.removed_title"), { title: landing.type === "removed" ? landing.title : "" });
  const body = result
    ? result.problem
      ? result.problem
      : ready || result.kind === "plugin"
        ? t(`marketplace.landed_${result.kind}`)
        : t("marketplace.landed_needs_connect")
    : null;
  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 z-50 flex justify-center p-5">
      <div
        role="status"
        className="pointer-events-auto flex w-full max-w-lg items-center gap-3 rounded-xl border border-border-strong bg-popover py-2.5 pl-4 pr-2 shadow-float"
      >
        {warn ? (
          <AlertTriangle className="h-4 w-4 shrink-0 text-warning" />
        ) : (
          <Check className="h-4 w-4 shrink-0 text-success" />
        )}
        <div className="min-w-0 flex-1">
          <p className="text-base font-medium text-foreground-strong">{title}</p>
          {body && <p className="text-base text-muted-foreground">{body}</p>}
        </div>
        {result && (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              onClose();
              setActiveSection(HOME_SECTION[result.kind] ?? "skills");
            }}
          >
            {t("marketplace.landed_open")}
          </Button>
        )}
        <Button size="icon" variant="ghost" onClick={onClose} aria-label={t("marketplace.close")} className="h-8 w-8">
          <X />
        </Button>
      </div>
    </div>
  );
}
