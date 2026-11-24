import { type ProviderDescriptor } from "@/hooks/useProviders";
import { useProviderTestStore, verificationOf, type Verification } from "@/store/providerTests";
import { cn } from "@/lib/utils";
import { useT } from "@/i18n";

// One calm chip vocabulary for every card state. Sentence-case, small, and
// tonally consistent (gold = on, green = ready, neutral = untouched, red =
// broken) — replaces the earlier mix of shouting uppercase badges.
/**
 * Status as a dot and a word, not a tinted capsule.
 *
 * `active` is the one chip that still frames itself (gold text, hairline),
 * because it is the one a user scans a list for. Everything else is a 7 px
 * dot in the semantic colour beside muted text — green means works, red means
 * blocked, grey means nothing to report — so six colours of pills collapse
 * into one quiet vocabulary. Semantic colour stays separate from the gold
 * accent: gold is "selected", never "healthy".
 */
export const STATE_CHIP_TONE = {
  active: {
    wrap: "rounded-[4px] border border-border-strong px-1.5 text-micro font-semibold text-foreground-strong",
    dot: null,
  },
  ready: { wrap: "text-muted-foreground", dot: "bg-muted-foreground" },
  missing: { wrap: "text-destructive", dot: "bg-destructive" },
  neutral: { wrap: "text-muted-foreground", dot: "bg-muted-foreground/50" },
} as const;

export function StateChip({
  tone,
  title,
  children,
}: {
  tone: keyof typeof STATE_CHIP_TONE;
  title?: string;
  children: React.ReactNode;
}) {
  const meta = STATE_CHIP_TONE[tone];
  return (
    <span
      title={title}
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap text-xs leading-5",
        meta.wrap,
      )}
    >
      {meta.dot && (
        <span aria-hidden="true" className={cn("h-[7px] w-[7px] rounded-full", meta.dot)} />
      )}
      {children}
    </span>
  );
}

/**
 * A small uppercase label for a property of the row — Recommended, Beta,
 * Optional, Not recommended. Hairline and text, no fill: at most one of these
 * per row carries meaning, and a row of filled capsules carried none.
 */
export function Tag({
  tone,
  title,
  children,
  ...rest
}: {
  tone: "accent" | "neutral" | "warn";
  title?: string;
  children: React.ReactNode;
  "data-testid"?: string;
}) {
  return (
    <span
      {...rest}
      title={title}
      className={cn(
        "inline-flex shrink-0 items-center rounded-[4px] border px-1.5 text-micro font-semibold leading-[18px] tracking-[0.06em]",
        tone === "accent" && "border-border-strong text-foreground-strong",
        tone === "neutral" && "border-border text-muted-foreground",
        tone === "warn" && "border-border-strong text-foreground",
      )}
    >
      {children}
    </span>
  );
}

/**
 * The card's state chip vocabulary — the summary a user actually scans.
 *
 * Every member maps to one `apikeys_view.state_*` key present in en/de/es
 * (pinned by `provider-state-chip-parity.test.ts`). These used to be bare
 * English literals, so a translated card carried an untranslated chip.
 */
export const PROVIDER_STATE_CHIPS = {
  active: { tone: "active", key: "apikeys_view.state_active" },
  // "ready" is a VERDICT, not a presence check: the provider answered a real
  // call (this session's Test, the on-disk runtime probe, or a CLI that
  // reports its login). A stored key alone is "key_saved" — grey, not green.
  ready: { tone: "ready", key: "apikeys_view.state_ready" },
  key_saved: { tone: "neutral", key: "apikeys_view.state_key_saved" },
  no_key: { tone: "neutral", key: "apikeys_view.state_no_key" },
  not_working: { tone: "missing", key: "apikeys_view.state_not_working" },
  not_installed: { tone: "missing", key: "apikeys_view.state_not_installed" },
  local: { tone: "neutral", key: "apikeys_view.state_local" },
  checking: { tone: "neutral", key: "apikeys_view.state_checking" },
  unavailable: { tone: "neutral", key: "apikeys_view.state_unavailable" },
  blocked: { tone: "missing", key: "apikeys_view.state_blocked" },
  missing: { tone: "missing", key: "apikeys_view.state_missing" },
  not_connected: { tone: "neutral", key: "apikeys_view.state_not_connected" },
  open: { tone: "neutral", key: "apikeys_view.state_open" },
} as const satisfies Record<
  string,
  { tone: keyof typeof STATE_CHIP_TONE; key: string }
>;

export type ProviderStateChip = keyof typeof PROVIDER_STATE_CHIPS;

/**
 * Which chip a descriptor deserves. Pure, so the mapping stays testable.
 *
 * `verification` is what this session's live Test found (see
 * store/providerTests.ts); without one, a hosted provider with a key is
 * "key_saved" — the chip says exactly as much as the app knows. Local engines
 * and login CLIs carry their own probe, so they can honestly say ready.
 */
export function providerStateChip(
  descriptor: ProviderDescriptor,
  verification: Verification = null,
): ProviderStateChip {
  // Selection alone proves neither a saved key nor a connected account.
  if (descriptor.active && descriptor.configured) return "active";
  if (descriptor.auth_mode === "codex") {
    const status = descriptor.codex_status;
    // Transient: the status is being probed right now. Neither "missing" nor
    // "not connected" is known yet, and the red chip on a healthy install was
    // exactly the bug this state exists to prevent.
    if (status?.reason_code === "busy") return "checking";
    // Nothing is "missing" on an OS the feature does not support at all.
    if (status?.reason_code === "lifecycle_unavailable") return "unavailable";
    // Terminal until the account changes — "not connected" would undersell it.
    if (status?.reason_code === "plan_unsupported") return "blocked";
    if (!status?.installed) return "missing";
    return descriptor.configured ? "ready" : "not_connected";
  }
  if (descriptor.auth_mode === "antigravity") {
    const status = descriptor.antigravity_status;
    if (!status?.installed) return "missing";
    return status.connected ? "ready" : "not_connected";
  }
  // OpenCode owns its model access: an installed CLI is ready.
  if (descriptor.auth_mode === "opencode" && !verification) {
    return descriptor.configured ? "ready" : "not_installed";
  }
  // A live verdict outranks everything below: the provider was asked and
  // answered (or did not).
  if (verification === "failed") return "not_working";
  if (verification === "ok" && descriptor.configured) return "ready";
  // On-device engine: the server's on-disk probe is the verdict.
  if (descriptor.local_runtime) {
    return descriptor.local_runtime.ready ? "ready" : "not_installed";
  }
  // Managed self-hosted server: installed and smoke-booted, or not there.
  if (descriptor.managed_server) {
    return descriptor.managed_server.ready ? "ready" : "not_installed";
  }
  // Jarvis-owned local voice engine: set up on this machine, or not.
  if (descriptor.voice_engine) {
    return descriptor.voice_engine.installed ? "ready" : "not_installed";
  }
  // A keyless provider (Ollama, a local OpenAI-compatible server you point
  // at) has nothing to store and, without a probe in its payload, nothing
  // proven either: it needs no key, and a Test decides the rest.
  if (descriptor.auth_mode === "none") return "local";
  return descriptor.configured ? "key_saved" : "no_key";
}

export function StatusBadge({ descriptor }: { descriptor: ProviderDescriptor }) {
  const t = useT();
  const tested = useProviderTestStore((s) => s.results[descriptor.id]);
  const chip = PROVIDER_STATE_CHIPS[providerStateChip(descriptor, verificationOf(tested))];
  return (
    <StateChip tone={chip.tone} title={tested?.detail || undefined}>
      {t(chip.key)}
    </StateChip>
  );
}
