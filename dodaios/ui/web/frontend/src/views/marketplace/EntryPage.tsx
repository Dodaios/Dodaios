/**
 * One entry, on a page of its own.
 *
 * This is the trust boundary. Everything published here is third-party
 * content that passed automated checks and no human review, so the page puts
 * the publisher, what the entry reaches, and the published files themselves
 * in front of the reader. The install button sits at the top, but nothing on
 * a list row installs: the way to the button leads through this page.
 */
import { useEffect, useRef, type ReactNode } from "react";
import { AlertTriangle, ArrowUpRight, Check, Loader2, MoreHorizontal, ShieldAlert, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ActionMenu, BackLink, IconButton } from "@/components/extensions/primitives";
import { FileCard } from "@/components/extensions/FileCard";
import { PublisherAvatar } from "@/components/marketplace/PublishIdentity";
import { localeForUiLanguage } from "@/components/runs/format";
import { fill, useI18nStore } from "@/i18n";
import { openExternalUrl } from "@/lib/openExternal";
import { useEntryContents } from "./api";
import { EntryMark } from "./EntryMark";
import { categoryLabel, type Entry } from "./model";

type Translate = (key: string) => string;

/** A date in the app's UI language — not the operating system's. */
export function formatDate(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleDateString(localeForUiLanguage(useI18nStore.getState().ui), {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/** The publisher's picture: by account id when known, so a rename keeps it. */
function avatarUrl(entry: Entry): string | null {
  if (entry.publisherId) return `https://avatars.githubusercontent.com/u/${entry.publisherId}?s=64`;
  return entry.publisher ? `https://github.com/${encodeURIComponent(entry.publisher)}.png?size=64` : null;
}

export interface EntryPageProps {
  entry: Entry;
  t: Translate;
  onBack: () => void;
  onInstall: () => void;
  onRemove: () => void;
  onOpenHome: () => void;
  installing: boolean;
  removing: boolean;
  /** What the last install or removal of THIS entry failed with. */
  actionError: string | null;
}

export function EntryPage(props: EntryPageProps) {
  const { entry, t } = props;
  const contents = useEntryContents(entry.name);
  const titleId = `marketplace-entry-${entry.kind}-${entry.name}`;
  const pageRef = useRef<HTMLDivElement>(null);
  // The parent hands a fresh `onBack` every render (the index refetches each
  // minute); the key handler below must be bound once per opening.
  const backRef = useRef(props.onBack);
  backRef.current = props.onBack;

  useEffect(() => {
    pageRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      // A menu or a dialog above the page answers Escape first.
      if (document.querySelector('[role="menu"], [role="dialog"][aria-modal="true"]')) return;
      backRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const facts: { label: string; value: string }[] = [];
  if (entry.version) facts.push({ label: t("marketplace.fact_version"), value: entry.version });
  if (entry.publishedAt) {
    facts.push({ label: t("marketplace.fact_published"), value: formatDate(entry.publishedAt) });
  }
  if (entry.categories.length > 0) {
    facts.push({
      label: t("marketplace.fact_category"),
      value: entry.categories.map(categoryLabel).join(", "),
    });
  }

  const files = contents.data?.files ?? [];
  const filesError = contents.error
    ? (contents.error as Error).message
    : contents.data?.error && files.length === 0
      ? contents.data.error
      : null;

  return (
    <ScrollArea className="min-h-0 flex-1">
      <article
        ref={pageRef}
        tabIndex={-1}
        aria-labelledby={titleId}
        data-testid="marketplace-entry"
        className="mx-auto w-full max-w-[860px] px-6 pb-24 pt-1 outline-none motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-bottom-1 motion-safe:duration-200"
      >
        <BackLink label={t("marketplace.title")} onClick={props.onBack} />
        <header className="mt-6 flex flex-wrap items-start gap-x-5 gap-y-4">
          <EntryMark entry={entry} size="page" />
          <div className="min-w-0 flex-1 basis-[260px]">
            <h1 id={titleId} className="font-display text-2xl font-semibold text-foreground-strong">
              {entry.title}
            </h1>
            <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-base text-muted-foreground">
              <span>{t(`marketplace.kind_${entry.kind}`)}</span>
              {entry.publisher && (
                <>
                  <span aria-hidden>·</span>
                  <PublisherAvatar login={entry.publisher} url={avatarUrl(entry)} size={18} className="ring-0" />
                  <span>@{entry.publisher}</span>
                </>
              )}
            </p>
          </div>
          <EntryAction {...props} />
        </header>

        {props.actionError && (
          <p role="alert" className="mt-4 flex items-start gap-2 text-base text-destructive">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            {props.actionError}
          </p>
        )}

        <p
          className={
            entry.description
              ? "mt-6 max-w-[68ch] text-reading text-foreground"
              : "mt-6 text-reading text-foreground-faint"
          }
        >
          {entry.broken
            ? (entry.problem ?? t("marketplace.entry_unreadable"))
            : (entry.description ?? t("marketplace.description_missing"))}
        </p>

        {facts.length > 0 && (
          <dl className="mt-6 flex flex-wrap gap-x-12 gap-y-3 border-y border-border py-4">
            {facts.map((fact) => (
              <div key={fact.label}>
                <dt className="text-sm text-muted-foreground">{fact.label}</dt>
                <dd className="mt-0.5 text-base font-medium text-foreground">{fact.value}</dd>
              </div>
            ))}
          </dl>
        )}

        <Reach entry={entry} t={t} />

        <Section title={t("marketplace.section_trust")}>
          <p className="flex max-w-[68ch] items-start gap-2.5 text-base text-foreground">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            {t("marketplace.unreviewed_note")}
          </p>
          {entry.sourceUrl && (
            <button
              type="button"
              onClick={() => openExternalUrl(entry.sourceUrl as string)}
              className="ml-[26px] mt-2 inline-flex items-center gap-1 rounded-sm text-base font-medium text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {t("marketplace.view_source")}
              <ArrowUpRight className="h-4 w-4" />
            </button>
          )}
        </Section>

        <Section title={t("marketplace.files")}>
          {contents.data?.error && files.length > 0 && (
            <p role="alert" className="mb-3 flex items-start gap-2 text-base text-foreground">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
              {contents.data.error}
            </p>
          )}
          <FileCard
            rootLabel={entry.name}
            files={files}
            loading={contents.isLoading}
            error={filesError}
            emptyLabel={t("marketplace.files_none")}
            tree="auto"
          />
        </Section>

        {entry.postInstallHint && (
          <Section title={t("marketplace.section_after")}>
            <p className="max-w-[68ch] whitespace-pre-line text-base text-foreground">
              {entry.postInstallHint}
            </p>
          </Section>
        )}
      </article>
    </ScrollArea>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="mb-3 text-lg font-semibold text-foreground-strong">{title}</h2>
      {children}
    </section>
  );
}

/** The one thing to do with this entry right now. */
function EntryAction({
  entry,
  t,
  onInstall,
  onRemove,
  onOpenHome,
  installing,
  removing,
}: EntryPageProps) {
  if (entry.broken) return null;

  // The app ships this service itself. The registry entry of the same name
  // cannot be installed over it, so the page offers the way to the real one.
  if (entry.seedConflict) {
    return (
      <Button variant="outline" onClick={onOpenHome} className="shrink-0">
        {fill(t("marketplace.open_in"), { section: t("marketplace.filter_plugins") })}
        <ArrowUpRight />
      </Button>
    );
  }

  if (entry.installed && !entry.updateAvailable) {
    const home = t(
      entry.kind === "plugin"
        ? "marketplace.filter_plugins"
        : entry.kind === "skill"
          ? "marketplace.filter_skills"
          : "marketplace.filter_agents",
    );
    return (
      <div className="flex shrink-0 items-center gap-2">
        <span className="inline-flex items-center gap-1.5 pr-1 text-base text-muted-foreground">
          <Check className="h-4 w-4 text-success" />
          {t("marketplace.installed")}
        </span>
        <Button variant="outline" onClick={onOpenHome}>
          {fill(t("marketplace.open_in"), { section: home })}
          <ArrowUpRight />
        </Button>
        {/* An agent is a teammate with a history; it is let go from Agents. */}
        {entry.kind !== "agent" && (
          <ActionMenu
            label={t("marketplace.more_actions")}
            actions={[
              {
                id: "remove",
                label: t("marketplace.remove"),
                icon: <Trash2 className="h-3.5 w-3.5" />,
                destructive: true,
                onSelect: onRemove,
              },
            ]}
            trigger={({ toggle }) => (
              <IconButton label={t("marketplace.more_actions")} onClick={toggle} busy={removing}>
                <MoreHorizontal className="h-4 w-4" />
              </IconButton>
            )}
          />
        )}
      </div>
    );
  }

  return (
    <div className="flex shrink-0 flex-col items-end gap-1.5">
      <Button size="lg" onClick={onInstall} disabled={installing} className="min-w-[132px]">
        {installing && <Loader2 className="animate-spin" />}
        {entry.updateAvailable
          ? fill(t("marketplace.update_to"), { version: entry.version ?? "" })
          : t("marketplace.install")}
      </Button>
      {entry.updateAvailable && entry.installedVersion && (
        <span className="text-sm text-muted-foreground">
          {fill(t("marketplace.installed_version"), { version: entry.installedVersion })}
        </span>
      )}
    </div>
  );
}

/** Mirrors the plugin consent dialog's labels — one vocabulary for one act. */
const AUTH_MODE_LABEL: Record<string, string> = {
  pat_paste: "plugins_community.auth_pat",
  oauth_device_flow: "plugins_community.auth_device",
  hosted_mcp_oauth_dcr: "plugins_community.auth_oauth",
  oauth_pkce_loopback: "plugins_community.auth_oauth",
  hosted_mcp_allowlist: "plugins_community.auth_allowlist",
};

/**
 * What installing this would actually reach.
 *
 * A plugin is a door to somebody else's service: the address its requests and
 * access token go to, or the command it would run on this computer. A file
 * listing alone does not tell anybody where their data ends up, so this says
 * it verbatim.
 */
function Reach({ entry, t }: { entry: Entry; t: Translate }) {
  const rows: { label: string; value?: string; code?: string; text?: string }[] = [];

  if (entry.kind === "plugin" && !entry.broken) {
    const mcp = entry.mcp;
    if (mcp?.transport === "stdio") {
      rows.push({ label: t("marketplace.runs_command"), code: (mcp.install ?? []).join(" ") });
    } else if (mcp?.url) {
      rows.push({ label: t("marketplace.sends_data_to"), code: mcp.url });
    } else {
      rows.push({ label: t("marketplace.metadata_only") });
    }
    const auth = entry.authMode ? AUTH_MODE_LABEL[entry.authMode] : undefined;
    if (auth) rows.push({ label: t("marketplace.sign_in_method"), value: t(auth) });
  }

  if (entry.kind === "agent" && entry.agent) {
    rows.push({ label: t("marketplace.agent_model") });
    if (entry.agent.focus.length > 0) {
      rows.push({ label: t("marketplace.agent_focus"), value: entry.agent.focus.join(", ") });
    }
    rows.push({
      label: t("marketplace.agent_asks"),
      value:
        entry.agent.require_approval.length > 0
          ? entry.agent.require_approval.join(", ")
          : t("marketplace.agent_asks_default"),
    });
    rows.push({ label: t("marketplace.agent_instructions"), text: entry.agent.instructions });
  }

  if (entry.portableAgents) {
    rows.push({
      label: t("marketplace.portable_skill"),
      value:
        entry.portableAgents.length > 0
          ? entry.portableAgents.join(", ")
          : t("marketplace.portable_any"),
    });
  }

  if (rows.length === 0) return null;

  return (
    <Section title={entry.kind === "plugin" ? t("marketplace.section_data") : t("marketplace.section_runs")}>
      <div className="space-y-4">
        {entry.seedConflict && (
          <p className="flex items-start gap-2 text-base text-foreground">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            {t("marketplace.seed_conflict")}
          </p>
        )}
        {rows.map((row) => (
          <div key={row.label}>
            <p className="text-base text-muted-foreground">{row.label}</p>
            {row.code && (
              <code className="mt-1.5 block break-all rounded-lg bg-secondary px-3 py-2 font-mono text-sm text-foreground">
                {row.code}
              </code>
            )}
            {row.text && (
              <p className="mt-1.5 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-secondary px-3 py-2 text-base text-foreground">
                {row.text}
              </p>
            )}
            {row.value && <p className="mt-0.5 text-base font-medium text-foreground">{row.value}</p>}
          </div>
        ))}
      </div>
    </Section>
  );
}
