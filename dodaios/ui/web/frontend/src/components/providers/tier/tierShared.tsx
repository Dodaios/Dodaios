import { useMemo } from "react";
import { Brain, ChevronDown, HardDrive, Mic, Radio, Sparkles, Terminal, Volume2, Wand2 } from "lucide-react";
import { type ProviderDescriptor, type ProviderTier, type SectionHealth, sectionHealthForSubject, useSectionHealth } from "@/hooks/useProviders";
import { useT } from "@/i18n";

export type LucideIcon = typeof Brain;

export interface CategoryMeta {
  /** Short label for the segmented tab. */
  tab: string;
  /** Full heading shown in the category hero band. */
  title: string;
  /** One-line plain-language description under the heading. */
  description: string;
  icon: LucideIcon;
}

// Meta for the three provider tiers (brain/tts/stt). Subagents and Advanced are
// composed separately because they own their own data sources / sub-sections.
export function makeProviderCategories(
  t: (k: string) => string,
): Record<ProviderTier, CategoryMeta> {
  return {
    brain: {
      tab: t("apikeys_view.tab_brain"),
      title: t("apikeys_view.tier_brain"),
      description: t("apikeys_view.cat_brain_desc"),
      icon: Brain,
    },
    tts: {
      tab: t("apikeys_view.tab_tts"),
      title: t("apikeys_view.tier_tts"),
      description: t("apikeys_view.cat_tts_desc"),
      icon: Volume2,
    },
    stt: {
      tab: t("apikeys_view.tab_stt"),
      title: t("apikeys_view.tier_stt"),
      description: t("apikeys_view.cat_stt_desc"),
      icon: Mic,
    },
    realtime: {
      tab: t("apikeys_view.tab_realtime"),
      title: t("apikeys_view.tier_realtime"),
      description: t("apikeys_view.cat_realtime_desc"),
      icon: Radio,
    },
    "computer-use": {
      tab: t("apikeys_view.tab_computer_use"),
      title: t("apikeys_view.tier_computer_use"),
      description: t("apikeys_view.cat_computer_use_desc"),
      icon: Terminal,
    },
    // The one OPTIONAL tier. Its description has to carry that, because an
    // empty section in a screen full of required keys reads as "you still have
    // work to do" — here it only means the dictation arrives exactly as it was
    // recognized, which is what every install did before this tier existed.
    dictation: {
      tab: t("apikeys_view.tab_dictation"),
      title: t("apikeys_view.tier_dictation"),
      description: t("apikeys_view.cat_dictation_desc"),
      icon: Wand2,
    },
  };
}

/**
 * Per-tab health (amber = the active provider isn't set up, red = it's set up
 * but failing a live check), re-bound to the provider that is ACTUALLY active
 * right now. Best-effort and off the render-blocking path.
 *
 * The re-bind is load-bearing, not cosmetic: the backend rollup carries the
 * `subject_id` it tested, and a stale entry (e.g. a NVIDIA timeout recorded
 * before the user switched to OpenRouter) must be DROPPED rather than
 * attributed to whoever is active now. Handing raw rollup entries to the tabs
 * re-opens exactly that bug.
 */
export function useTierHealth(
  providers: ProviderDescriptor[],
): Record<string, SectionHealth> {
  const { health: rawHealth } = useSectionHealth();
  return useMemo(() => {
    const visible = { ...rawHealth };
    const activeSubjects: Record<string, string | undefined> = {
      brain: providers.find((provider) => provider.tier === "brain" && provider.active)?.id,
      tts: providers.find((provider) => provider.tier === "tts" && provider.active)?.id,
      stt: providers.find((provider) => provider.tier === "stt" && provider.active)?.id,
      realtime: providers.find(
        (provider) => provider.tier === "realtime" && provider.active,
      )?.id,
      "computer-use": providers.find(
        (provider) => provider.tier === "brain" && provider.computer_use_active,
      )?.id,
      // "dictation" is deliberately absent. Its default pin is "auto", where no
      // single card is chosen and the family that answers is decided per call by
      // the key-aware chain — so there is no local "active id" to re-bind
      // against, and dropping the entry for want of one would hide a real
      // failure. The backend rollup names the family it tested in `subject_id`,
      // and `TierSection` only ever hands health to a card that matches it, so
      // the card-level drill-down still cannot blame the wrong provider.
    };
    for (const [section, subjectId] of Object.entries(activeSubjects)) {
      const matching = sectionHealthForSubject(rawHealth[section], subjectId);
      if (matching) visible[section] = matching;
      else delete visible[section];
    }
    return visible;
  }, [providers, rawHealth]);
}

/**
 * The one line that explains a shorter card list. Without it, a user who
 * forgot the switch is on reads the missing hosted cards as a broken install —
 * so the notice states the count, and carries the switch-off action itself.
 */
export function LocalModeNotice({
  hiddenCount,
  keptActiveHosted,
  onDisable,
}: {
  hiddenCount: number;
  keptActiveHosted: boolean;
  onDisable: () => void;
}) {
  const t = useT();
  return (
    <div
      data-testid="local-mode-notice"
      // The count as a plain attribute as well as in the sentence: the sentence
      // is a translated template, so this is the one place a test (or a support
      // screenshot) can read the number without depending on wording.
      data-hidden-count={hiddenCount}
      className="mb-3 flex items-start gap-2.5 rounded-surface border border-border bg-card px-3 py-2"
    >
      <HardDrive aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
      <p className="min-w-0 text-xs leading-relaxed text-muted-foreground">
        <span className="font-medium text-foreground">
          {t("apikeys_view.local_mode_label")}
        </span>{" "}
        · {t("apikeys_view.local_mode_notice").replace("{0}", String(hiddenCount))}
        {keptActiveHosted && ` ${t("apikeys_view.local_mode_notice_active")}`}{" "}
        <button
          type="button"
          onClick={onDisable}
          className="font-medium text-foreground-strong underline-offset-2 hover:underline"
        >
          {t("apikeys_view.local_mode_show_all")}
        </button>
      </p>
    </div>
  );
}

/**
 * The header band atop each category panel: an icon chip, the full category
 * title (display font), and a one-line plain-language description. Mirrors the
 * app's `ViewHeader` icon treatment so the screen reads as one system.
 */
export function CategoryHero({
  icon: Icon,
  title,
  description,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
}) {
  // The tab already names the category, so the heading here is a kicker, not
  // a hero: icon, title and the one-line description on a single baseline.
  return (
    <div className="mb-3 flex min-w-0 items-center gap-2 pt-1">
      <Icon aria-hidden="true" className="h-4 w-4 shrink-0 text-muted-foreground" />
      <h3 className="shrink-0 font-display text-sm font-semibold tracking-tight">
        {title}
      </h3>
      <span aria-hidden="true" className="text-border">·</span>
      <p className="min-w-0 truncate text-xs text-muted-foreground" title={description}>
        {description}
      </p>
    </div>
  );
}

/**
 * The "which one should I pick?" guidance — the one place a category speaks
 * up with an opinion. Used by the Realtime and Computer-Use tabs, where the
 * model choice genuinely confuses people; the calmer tiers carry their
 * guidance on the cards themselves (Recommended tags).
 *
 * A disclosure, closed by default: the question is the visible part, the
 * answer opens on demand. It used to be a permanently open tinted band above
 * every card list — advice nobody asked for, on every visit.
 */
export function GuidancePanel({ title, body }: { title: string; body: string }) {
  return (
    <details className="group mb-3 text-xs">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 font-medium text-foreground transition-colors hover:text-foreground [&::-webkit-details-marker]:hidden">
        <Sparkles aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        {title}
        <ChevronDown
          aria-hidden="true"
          className="h-3 w-3 text-muted-foreground transition-transform group-open:rotate-180 motion-reduce:transition-none"
        />
      </summary>
      <p className="mt-1.5 max-w-prose pl-5 leading-relaxed text-muted-foreground">{body}</p>
    </details>
  );
}
