import { useState } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import { type ProviderDescriptor, type ProviderTier, type SectionHealth, PROVIDER_BACKEND_UNREACHABLE, sectionHealthForSubject } from "@/hooks/useProviders";
import { filterForLocalMode } from "@/lib/localMode";
import { cn } from "@/lib/utils";
import { useT } from "@/i18n";
import { type CategoryMeta, LocalModeNotice, CategoryHero } from "./tierShared";
import { ProviderCard } from "./ProviderCard";

/**
 * One of the three provider tiers (brain/tts/stt): the hero band plus the
 * loading / error / empty / card states. The card list itself is `TierSection`,
 * reused unchanged from the original layout.
 */
export function ProviderCategory({
  meta,
  tier,
  providers,
  loading,
  error,
  onChanged,
  onActivateOptimistic,
  health,
  intro,
  localMode = false,
  onDisableLocalMode,
  wideGrid = false,
}: {
  meta: CategoryMeta;
  tier: ProviderTier;
  providers: ProviderDescriptor[];
  loading: boolean;
  error: string | null;
  onChanged: () => void;
  onActivateOptimistic: (tier: ProviderTier, id: string) => void;
  /** Live health of this tier's ACTIVE provider — drills the tab's red dot down
   *  onto the exact card that is failing so the user sees WHICH provider broke. */
  health?: SectionHealth;
  /** Optional guidance band rendered between the hero and the card list. */
  intro?: React.ReactNode;
  /** Show only cards that run on the user's own hardware. Presentation only —
   *  defaults off so every existing caller renders the full catalog. */
  localMode?: boolean;
  /** Turns Local Mode back off from the notice above the list. */
  onDisableLocalMode?: () => void;
  wideGrid?: boolean;
}) {
  const t = useT();
  const allTierProviders = providers.filter(
    (p) => p.tier === tier && p.brain_switchable !== false,
  );
  const {
    visible: tierProviders,
    hiddenCount,
    keptActiveHosted,
  } = filterForLocalMode(allTierProviders, localMode);

  return (
    <div role="tabpanel">
      <CategoryHero icon={meta.icon} title={meta.title} description={meta.description} />

      {/* Above the guidance band: the shorter list has to be explained before
          the user starts scanning it, not after. */}
      {localMode && hiddenCount > 0 && (
        <LocalModeNotice
          hiddenCount={hiddenCount}
          keptActiveHosted={keptActiveHosted}
          onDisable={() => onDisableLocalMode?.()}
        />
      )}

      {intro}

      {loading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> {t("apikeys_view.loading_providers")}
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2 rounded-md bg-secondary p-4 text-sm text-destructive">
          <AlertCircle className="mt-0.5 h-4 w-4" />
          <div>
            {error === PROVIDER_BACKEND_UNREACHABLE
              ? t("apikeys_view.backend_unavailable")
              : `${t("apikeys_view.load_error")} (${error}).`}
            <button onClick={() => onChanged()} className="ml-2 underline">
              {t("apikeys_view.retry")}
            </button>
          </div>
        </div>
      )}

      {!loading && !error && tierProviders.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {t("apikeys_view.no_providers_in_tier")}
        </p>
      )}

      {!loading && !error && tierProviders.length > 0 && (
        <TierSection
          providers={tierProviders}
          onChanged={onChanged}
          onActivateOptimistic={onActivateOptimistic}
          health={health}
          wideGrid={wideGrid}
        />
      )}
    </div>
  );
}

// The card list for a single provider tier. The category label now lives in the
// tab bar + the `CategoryHero` above, so this renders only the cards. If nobody
// in the tier is active yet, a freshly saved key auto-activates itself — the
// first configured provider wins automatically (`autoActivateOnSave`).
export function TierSection({
  providers,
  onChanged,
  onActivateOptimistic,
  health,
  wideGrid = false,
}: {
  providers: ProviderDescriptor[];
  onChanged: () => void;
  onActivateOptimistic: (tier: ProviderTier, id: string) => void;
  /** Tier health — handed only to the ACTIVE card, since section-health tests
   *  exactly the one provider powering this tier. */
  health?: SectionHealth;
  wideGrid?: boolean;
}) {
  const tierHasActive = providers.some((p) => p.active);
  // The provider this tier actually RUNS on leads the list. Somebody who just
  // picked one — onboarding's local path being the sharpest case — has to find
  // it at the top, not somewhere inside the catalog order below cards they
  // never touched. Capability-driven: whatever is active leads, no provider id
  // is named here (AP-21).
  //
  // Anchored on the id that was active when this list FIRST rendered, never on
  // the live one: re-sorting on every change would yank a card to the top
  // under the pointer the moment it is activated. The anchor re-arms when the
  // tier is re-entered (the view remounts this list per tab/mode change), so
  // the next visit leads with the new choice.
  const [leadId] = useState<string | null>(
    () => providers.find((p) => p.active)?.id ?? null,
  );
  // Configured (or active) providers next — the wall of empty key forms used
  // to bury the one or two cards the user actually set up. `active` counts so
  // an active-but-keyless anomaly (e.g. a free-tier provider) can never hide
  // below untouched cards; among configured cards nothing reorders on a switch
  // (both stay rank 0), so a card never jumps under the pointer mid-click.
  // Stable within each group (Array.sort is stable).
  const rank = (p: ProviderDescriptor) =>
    p.id === leadId ? 2 : Number(p.configured || p.active);
  const sorted = [...providers].sort((a, b) => rank(b) - rank(a));
  // One row open at a time. The list opens on the provider this tier RUNS on
  // (or, in an empty tier, on the first card, so there is a key field on
  // screen to paste into); every other provider is a scannable one-line row
  // until it is clicked. This is what turns 2 000 px of stacked forms into a
  // list the eye can read top to bottom.
  const [expandedId, setExpandedId] = useState<string | null>(
    () => leadId ?? sorted[0]?.id ?? null,
  );
  return (
    <ul
      data-testid="provider-list"
      className={cn(
        wideGrid
          ? "grid items-start gap-3"
          : "divide-y divide-border/70 overflow-hidden rounded-surface border border-border bg-card",
      )}
      style={wideGrid ? { gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 34rem), 1fr))" } : undefined}
    >
      {sorted.map((p) => (
        <li
          key={p.id}
          className={wideGrid ? "min-w-0 overflow-hidden rounded-surface border border-border bg-card" : undefined}
        >
          <ProviderCard
            descriptor={p}
            onChanged={onChanged}
            onActivateOptimistic={onActivateOptimistic}
            autoActivateOnSave={!tierHasActive}
            health={p.active ? sectionHealthForSubject(health, p.id) : undefined}
            expanded={expandedId === p.id}
            onToggleExpanded={() =>
              setExpandedId((current) => (current === p.id ? null : p.id))
            }
          />
        </li>
      ))}
    </ul>
  );
}
