import { useState, type ReactNode } from "react";
import { ChevronDown, KeyRound, XCircle } from "lucide-react";
import { BrainModelSelector } from "@/components/BrainModelSelector";
import { OpenRouterTtsControls } from "@/components/OpenRouterTtsVoicePicker";
import { RealtimeOptionsControl } from "@/components/RealtimeOptionsControl";
import { ProviderLogo } from "@/components/providers/ProviderLogo";
import { useRowGestures } from "@/components/providers/rowGestures";
import { type ProviderDescriptor, type ProviderTestResult, type ProviderTier, type SectionHealth, switchBrainProvider, switchComputerUseProvider, switchDictationPolishProvider, switchRealtimeProvider, switchSttProvider, switchTtsProvider, testProvider } from "@/hooks/useProviders";
import { useEventStore } from "@/store/events";
import { useProviderTestStore } from "@/store/providerTests";
import { agentBrand, agentsBrand } from "@/lib/agentBrand";
import { hasExperimentalConsent, rememberExperimentalConsent } from "@/lib/experimentalConsent";
import { requestRealtimeTransportOffer } from "@/lib/realtimeTransportIssue";
import { cn } from "@/lib/utils";
import { useT } from "@/i18n";
import { ProviderTestControl, ActiveControl, AuthWidget, CODEX_STATUS_KEY_BY_REASON } from "./ProviderControls";
import { Tag, StatusBadge } from "./ProviderChips";

export function ProviderCard({
  descriptor,
  onChanged,
  onActivateOptimistic,
  autoActivateOnSave,
  health,
  expanded = true,
  onToggleExpanded,
  configuration,
  hideCredentialControls = false,
  billingOverride,
  billingPending = false,
}: {
  descriptor: ProviderDescriptor;
  onChanged: () => void;
  onActivateOptimistic: (tier: ProviderTier, id: string) => void;
  autoActivateOnSave: boolean;
  /** Live section-health for THIS card (set only on the active provider). A
   *  status of "error" turns the card red and surfaces the cause inline — the
   *  tab dot says "something here is broken", this says exactly WHAT/WHERE. */
  health?: SectionHealth;
  /** Whether the editor body (key, model, test) is open under the row. A
   *  caller that renders a single card leaves it open; the tier list opens
   *  one row at a time. */
  expanded?: boolean;
  /** Toggles `expanded`; absent means the row is not collapsible. */
  onToggleExpanded?: () => void;
  /** Provider-owned setup shares the existing credential and verification controls. */
  configuration?: ReactNode;
  /** A provider-owned subscription editor supplies its own sign-in controls. */
  hideCredentialControls?: boolean;
  /** Display-only draft billing choice; never changes activation or auth. */
  billingOverride?: ProviderDescriptor["billing"];
  billingPending?: boolean;
}) {
  const t = useT();
  const [activating, setActivating] = useState(false);
  // The experimental-route acknowledgement. It used to be a window.confirm,
  // which the desktop WebView renders as a raw "127.0.0.1 says" box that also
  // blocks the whole window — and it reappeared on EVERY switch, which is the
  // confirmation fatigue this project explicitly rejects. Now it is an in-app
  // dialog shown once per provider.
  const [consentPending, setConsentPending] = useState(false);
  const pushToast = useEventStore((s) => s.pushToast);
  const assistantName = useEventStore((s) => s.assistantName);
  const recordVerdict = useProviderTestStore((s) => s.record);
  // The card only escalates to red for a real "set up but failing" error — the
  // amber "needs setup" case stays on the tab + the open/ready badge so a fresh,
  // half-configured screen doesn't paint cards red.
  const cardError = descriptor.active && health?.status === "error";
  // The backend one-liner (e.g. "OpenRouter: rate limited") already names the
  // provider + cause, so it answers "what is wrong" without a second lookup.
  const cardErrorDetail = health?.detail?.trim() || "";

  // The legacy Codex Brain card has stricter readiness rules than other
  // Codex-auth surfaces. Subscription Realtime uses the same login widget but
  // must remain activatable without an API key.
  const isCodexAuth = descriptor.auth_mode === "codex";
  const isCodexBrain = isCodexAuth && descriptor.tier === "brain";
  const isSubscriptionLoginOnly =
    isCodexAuth &&
    descriptor.billing === "subscription" &&
    descriptor.secret_keys.length === 0;
  const isBrainSwitchable =
    descriptor.tier !== "brain" || descriptor.brain_switchable !== false;

  /**
   * Prove the polish provider the user just picked can actually answer, and
   * say so when it cannot.
   *
   * Runs AFTER the switch, never as a gate: a probe that fails for its own
   * reasons must not be able to block a preference the user is entitled to
   * set. Never throws — a verification that breaks has to stay quieter than
   * the switch it is checking.
   */
  async function verifyPolishProvider() {
    let result: ProviderTestResult;
    try {
      result = await testProvider(descriptor.id);
    } catch (e) {
      // Not the user's problem and not evidence about the provider: say
      // nothing rather than raise a false alarm about a working switch.
      console.debug("polish provider verification failed to run", e);
      return;
    }
    recordVerdict(descriptor.id, result);
    if (result.status === "ok") return;
    // The backend's sentence already names the cause AND the fix ("no credits",
    // "model not pulled", "slower than the 1200 ms limit — raise it or pick a
    // faster provider"), so it is shown verbatim instead of being flattened
    // into a generic "does not work".
    pushToast(
      "warning",
      t("apikeys_view.polish_verify_failed")
        .replace("{0}", descriptor.label)
        .replace("{1}", result.detail || result.status),
    );
    // Let the card repaint with the health this test just produced.
    onChanged();
  }

  /** "<tier> → <provider>", plus the "from the next voice start" note. */
  function switchToast(key: string, restartRequired = false): string {
    const line = t(key).replace("{0}", descriptor.label);
    return restartRequired
      ? `${line}${t("apikeys_view.switch_note_next_start")}`
      : line;
  }

  async function activate(assumeConfigured = false) {
    // The Live profile saves the voice provider and thinking model together.
    if (descriptor.configuration_surface === "live") return;
    if (descriptor.active) return;
    if (!isBrainSwitchable) {
      pushToast(
        "warning",
        t("apikeys_view.agents_only_toast")
          .replace("{0}", descriptor.label)
          .replace("{1}", agentsBrand(assistantName)),
      );
      return;
    }
    if (isCodexBrain && !descriptor.codex_brain_ready) {
      // The card is "connected" via OAuth, but a chat brain needs an OpenAI key.
      // Guide honestly instead of switching and failing on the first turn.
      pushToast("warning", t("apikeys_codex.brain_needs_openai_key"));
      return;
    }
    if (
      !assumeConfigured &&
      !descriptor.configured &&
      // plan_unsupported deliberately proceeds to the backend switch: its
      // live account gate is the ONLY judge that can clear the sticky block
      // when the plan changed back; a re-refusal answers with the precise
      // 409 detail as an error toast.
      descriptor.codex_status?.reason_code !== "plan_unsupported"
    ) {
      const codexReason = descriptor.codex_status?.reason_code;
      // Transient/in-flight states are notes, not faults — and telling the
      // user to redo a working ChatGPT login would contradict the card's own
      // "checking" / "finish the login" line (and the backend's 409s).
      if (codexReason === "busy" || codexReason === "login_in_progress") {
        pushToast("info", t(CODEX_STATUS_KEY_BY_REASON[codexReason]));
        return;
      }
      pushToast(
        "warning",
        descriptor.auth_mode === "codex"
          ? isSubscriptionLoginOnly
            ? // The reason-specific line names the actual remedy (install the
              // pinned release, unsupported OS, unsupported plan…) — a blank
              // "connect first" would be wrong for most of those states.
              t(
                (codexReason &&
                  (CODEX_STATUS_KEY_BY_REASON as Record<string, string>)[
                    codexReason
                  ]) ||
                  "apikeys_codex.subscription_login_required",
              )
            : t("apikeys_codex.needs_codex_full").replace("{0}", descriptor.label)
          : descriptor.auth_mode === "antigravity"
            ? t("apikeys_antigravity.needs_login_full").replace("{0}", descriptor.label)
            : t("apikeys_codex.needs_key_full").replace("{0}", descriptor.label),
      );
      return;
    }
    // The experimental acknowledgement must come BEFORE the optimistic flip:
    // a declined dialog used to return early with the radio stuck on the new
    // card and no refetch to roll it back.
    const isRealtimeSwitch = !["brain", "tts", "stt", "computer-use", "dictation"].includes(
      descriptor.tier,
    );
    if (
      isRealtimeSwitch &&
      descriptor.experimental &&
      !hasExperimentalConsent(descriptor.id)
    ) {
      setConsentPending(true);
      return;
    }
    // Flip the highlight immediately so the switch feels instant — the backend
    // call below can take a few seconds (a TTS switch rebuilds the provider and
    // injects it into the live pipeline). The refetch on success / failure then
    // reconciles with server truth.
    onActivateOptimistic(descriptor.tier, descriptor.id);
    setActivating(true);
    try {
      if (descriptor.tier === "brain") {
        await switchBrainProvider(descriptor.id);
        pushToast("success", switchToast("apikeys_view.switch_done_brain"));
        window.dispatchEvent(new CustomEvent("jarvis:brain-switched"));
      } else if (descriptor.tier === "tts") {
        const result = await switchTtsProvider(descriptor.id);
        pushToast(
          "success",
          switchToast("apikeys_view.switch_done_tts", result.restart_required),
        );
        window.dispatchEvent(new CustomEvent("jarvis:tts-switched"));
      } else if (descriptor.tier === "stt") {
        const result = await switchSttProvider(descriptor.id);
        pushToast(
          "success",
          switchToast("apikeys_view.switch_done_stt", result.restart_required),
        );
        window.dispatchEvent(new CustomEvent("jarvis:stt-switched"));
      } else if (descriptor.tier === "computer-use") {
        await switchComputerUseProvider(descriptor.id);
        pushToast("success", switchToast("apikeys_view.switch_done_computer_use"));
        window.dispatchEvent(new CustomEvent("jarvis:computer-use-switched"));
      } else if (descriptor.tier === "dictation") {
        // Its own branch on purpose: this tier has no `/switch` route (the pin
        // is a plain `[dictation]` setting), and without the branch it would
        // fall through to the realtime switch below and reconfigure the user's
        // voice engine from a dictation card.
        //
        // `polish_family`, NOT `id`: the config stores "openai" while this card
        // is "openai-polish" (a bare "openai" is already the brain card). The
        // chain ignores a family id it does not know and quietly falls back to
        // the auto order, so sending `id` wrote a pin that returned HTTP 200,
        // showed a success toast, and left the previous provider active — the
        // exact "it says it did it but nothing changed" failure. Falling back to
        // `id` keeps an older payload without the field working.
        await switchDictationPolishProvider(descriptor.polish_family || descriptor.id);
        pushToast("success", switchToast("apikeys_view.switch_done_dictation"));
        window.dispatchEvent(new CustomEvent("jarvis:dictation-polish-switched"));
        // A stored key is not a working provider, and this tier is where the
        // gap bites hardest: the pass is INVISIBLE when it fails (it delivers
        // the raw transcript), so an out-of-credits account, a model the host
        // never pulled, or a family too slow for the latency budget all look
        // exactly like "active and fine" on the card. Measured on a real
        // install, four of five cards that read "ready" could not polish a
        // sentence. So the switch verifies itself and says what it found —
        // cheap here (a handful of tokens) and the only honest signal.
        void verifyPolishProvider();
      } else {
        // The switch reconnects an OPEN call synchronously, and an
        // offer-requiring transport cannot start without a registered browser
        // offer. Ask for one before the POST rather than after the reconnect
        // already failed. Dispatched for every realtime switch, never keyed on
        // a provider name (AP-21) — a transport that needs none ignores it.
        requestRealtimeTransportOffer();
        const result = await switchRealtimeProvider(
          descriptor.id,
          descriptor.experimental === true,
        );
        pushToast(
          "success",
          switchToast("apikeys_view.switch_done_realtime", result.restart_required),
        );
        window.dispatchEvent(new CustomEvent("jarvis:realtime-switched"));
      }
      onChanged();
    } catch (e) {
      pushToast("error", (e as Error).message);
      // Roll the optimistic highlight back to the true active provider.
      onChanged();
      window.dispatchEvent(
        new CustomEvent("jarvis:provider-switch-failed", {
          detail: { section: descriptor.tier, provider: descriptor.id },
        }),
      );
    } finally {
      setActivating(false);
    }
  }

  // One click on the row selects it: the editor body opens AND the provider
  // becomes the active one — the same path as the Use control. A click only
  // switches when the switch would be silent: a card without a key, a card
  // that cannot be switched (an agents-only brain, a Codex login that is not
  // a brain) or the already-active card just opens/closes — otherwise every
  // click to paste a key would answer with a "save a key first" warning. See
  // rowGestures.ts for the click semantics.
  const canSwitch = isBrainSwitchable && !isCodexBrain;
  const switchesOnClick =
    canSwitch && !descriptor.active && descriptor.configured && !activating;
  const rowGestures = useRowGestures({
    expanded,
    onToggle: onToggleExpanded,
    onActivate: switchesOnClick ? () => void activate() : undefined,
  });

  // Called by ApiKeyForm as soon as a key has been saved for a previously
  // unconfigured provider. If no one else is active in this tier, the
  // freshly configured provider takes over automatically — otherwise the
  // user has to click the now-visible "Activate" button.
  async function handleSavedActivate() {
    if (!autoActivateOnSave) return;
    if (descriptor.active) return;
    await activate(true);
  }

  const consentDialog = consentPending ? (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-scrim/60 p-4"
      onClick={(event) => {
        event.stopPropagation();
        setConsentPending(false);
      }}
    >
      <div
        className="card-outline max-w-lg space-y-4 bg-background p-5"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="text-sm font-semibold">{descriptor.label}</div>
        <p className="text-sm leading-relaxed text-muted-foreground">
          {t(
            isSubscriptionLoginOnly
              ? "apikeys_view.experimental_subscription_consent"
              : "apikeys_view.experimental_consent",
          )}
        </p>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            className="btn-outline px-3 py-1.5 text-sm"
            onClick={(event) => {
              event.stopPropagation();
              setConsentPending(false);
            }}
          >
            {t("common.cancel")}
          </button>
          <button
            type="button"
            className="btn-primary px-3 py-1.5 text-sm"
            onClick={(event) => {
              event.stopPropagation();
              rememberExperimentalConsent(descriptor.id);
              setConsentPending(false);
              void activate();
            }}
          >
            {t("common.yes")}
          </button>
        </div>
      </div>
    </div>
  ) : null;

  // The one-line summary under the name: how the card is paid for, in human
  // words. It used to be "gemini-live · API key auth" — the catalog id and
  // developer vocabulary; the id still travels on the row's testid and for
  // assistive tech, and the billing line already says how you sign in.
  const summary = t(`provider_billing.${billingOverride ?? descriptor.billing}`);
  const collapsible = Boolean(onToggleExpanded);
  const rowTitle = descriptor.active && !descriptor.configured
    ? t("apikeys_view.needs_credentials")
    : descriptor.active
    ? t("apikeys_view.active_tooltip")
    : !isBrainSwitchable
      ? t("apikeys_view.agents_only_short").replace("{0}", agentsBrand(assistantName))
      : descriptor.configured
        ? t("apikeys_view.click_to_activate")
        : descriptor.auth_mode === "codex"
          ? t("apikeys_view.needs_codex")
          : descriptor.auth_mode === "antigravity"
            ? t("apikeys_view.needs_login")
            : t("apikeys_view.needs_key");

  return (
    <>
    {consentDialog}
    <div
      data-testid={`provider-card-${descriptor.id}`}
      data-expanded={expanded ? "true" : "false"}
      className={cn(
        "relative transition-colors",
        // The active provider gets a 3 px gold rule on the left edge and a
        // faint wash — said once, at the edge, instead of three times
        // (chip + frame + tint). A broken active provider turns that rule red.
        cardError
          ? "bg-destructive/[0.04] before:absolute before:inset-y-2 before:left-0 before:w-[3px] before:rounded-r before:bg-destructive"
          : descriptor.active
            ? "bg-primary/[0.035] before:absolute before:inset-y-2 before:left-0 before:w-[3px] before:rounded-r before:bg-foreground/70"
            : "",
      )}
    >
      {/* ROW — logo, name, summary, state, the "Use" control, chevron. */}
      <div
        role={collapsible ? "button" : undefined}
        tabIndex={collapsible ? 0 : undefined}
        aria-expanded={collapsible ? expanded : undefined}
        aria-controls={collapsible ? `provider-body-${descriptor.id}` : undefined}
        data-testid={`provider-row-${descriptor.id}`}
        onClick={rowGestures.onClick}
        onKeyDown={(e) => {
          if (!collapsible) return;
          if (e.target !== e.currentTarget) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            rowGestures.select();
          }
        }}
        title={rowTitle}
        className={cn(
          "flex items-center gap-3 px-3.5 py-3 outline-none",
          collapsible && "cursor-pointer hover:bg-secondary focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
          !isBrainSwitchable && "opacity-80",
        )}
      >
        <ProviderLogo providerId={descriptor.id} label={descriptor.label} />

        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <span className="truncate font-display text-sm font-semibold tracking-tight">
              {descriptor.label}
            </span>
            {!descriptor.active && <StatusBadge descriptor={descriptor} />}
            {descriptor.recommended && (
              <Tag
                tone="accent"
                title={
                  descriptor.recommended_model
                    ? t("apikeys_view.recommended_tooltip").replace(
                        "{0}",
                        descriptor.recommended_model,
                      )
                    : undefined
                }
              >
                {t("apikeys_view.recommended")}
              </Tag>
            )}
            {descriptor.experimental && (
              <Tag
                tone="neutral"
                data-testid={`provider-experimental-${descriptor.id}`}
                title={t("apikeys_view.experimental_note")}
              >
                {t("apikeys_view.experimental")}
              </Tag>
            )}
            {descriptor.caution && (
              <Tag tone="warn" title={descriptor.caution}>
                {t("apikeys_view.not_recommended")}
              </Tag>
            )}
            {/* Neutral, never amber: an unset optional key is not a warning. */}
            {descriptor.optional && (
              <Tag
                tone="neutral"
                data-testid={`provider-optional-${descriptor.id}`}
                title={t("apikeys_view.optional_tooltip")}
              >
                {t("apikeys_view.optional")}
              </Tag>
            )}
          </div>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">
            {summary}
            {billingPending ? ` · ${t("live.billing_pending")}` : null}
            <span className="sr-only">{` · ${descriptor.id}`}</span>
          </p>
        </div>

        {descriptor.configuration_surface !== "live" && (
        <ActiveControl
          descriptor={
            isCodexBrain
              ? { ...descriptor, configured: Boolean(descriptor.codex_brain_ready) }
              : descriptor
          }
          activating={activating}
          onActivate={activate}
          disabled={
            !isBrainSwitchable || (isCodexBrain && !descriptor.codex_brain_ready)
          }
          disabledReason={
            !isBrainSwitchable
              ? t("apikeys_view.agents_only_short").replace(
                  "{0}",
                  agentsBrand(assistantName),
                )
              : isCodexBrain && !descriptor.codex_brain_ready
                ? t("apikeys_codex.brain_needs_openai_key")
                : undefined
          }
        />

        )}
        {collapsible && (
          <ChevronDown
            aria-hidden="true"
            className={cn(
              "h-4 w-4 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none",
              expanded && "rotate-180",
            )}
          />
        )}
      </div>

      {/* BODY — everything that edits the provider. Mounted only while open,
          so a collapsed list neither polls nor paints forty key forms. */}
      {expanded && (
        <div
          id={`provider-body-${descriptor.id}`}
          data-testid={`provider-body-${descriptor.id}`}
          className="space-y-3 border-t border-border bg-background px-3.5 pb-3.5 pl-[3.75rem] pt-3"
        >
          {/* The precise "this card is the problem" banner: only on the active card,
              only when the live check actually failed. Names the cause in plain
              words instead of leaving the user to guess behind the tab's red dot. */}
          {cardError && (
            <div
              data-testid={`provider-health-error-${descriptor.id}`}
              role="status"
              className="flex items-start gap-2 rounded-control border border-destructive/40 bg-destructive/[0.07] px-3 py-2 text-xs leading-relaxed text-destructive"
            >
              <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span className="min-w-0 break-words">
                <span className="font-medium">{t("apikeys_view.health_error")}</span>
                {cardErrorDetail ? ` — ${cardErrorDetail}` : ""}
              </span>
            </div>
          )}

          {/* The key row stays visible: a collapsed disclosure hid the only
              place to enter or replace the key behind a tiny triangle. */}
          {!hideCredentialControls && (configuration && descriptor.configured ? (
            <div data-testid={`provider-key-${descriptor.id}`} className="space-y-2 rounded-lg border border-border px-3 py-2.5">
              <p className="flex items-center gap-1.5 text-sm font-medium text-foreground">
                <KeyRound aria-hidden="true" className="h-3.5 w-3.5 text-muted-foreground" />
                {t("live.shared_key_ready")}
              </p>
              <AuthWidget descriptor={descriptor} onChanged={onChanged} onSavedActivate={handleSavedActivate} />
            </div>
          ) : <AuthWidget descriptor={descriptor} onChanged={onChanged} onSavedActivate={handleSavedActivate} />)}

          {configuration}

          {!isBrainSwitchable && (
            <p className="rounded-control bg-secondary px-3 py-2 text-xs leading-relaxed text-foreground">
              {t("apikeys_view.agents_only_note").replace(
                "{0}",
                agentBrand(assistantName),
              )}
            </p>
          )}

          {/* Model / voice picker. Every switchable brain provider shows its model
              picker — even before a key is set — because the catalog falls back to
              the provider's curated family without a key (no network, no error), so
              a model can be pre-picked. TTS/STT share a single global [tts]/[stt]
              block, so the picker only WRITES from the ACTIVE provider and sets the
              voice (Grok/Gemini/OpenAI/Google) or model (Cartesia/STT). */}
          {((descriptor.tier === "brain" && isBrainSwitchable) ||
            ((descriptor.tier === "tts" || descriptor.tier === "stt") &&
              descriptor.active &&
              descriptor.configured)) &&
            // OpenRouter TTS is the one provider where the user also picks a VOICE
            // (per model, language-tagged, with an audio preview) — render the
            // combined model + voice controls; every other tier keeps the plain
            // model/voice picker.
            (descriptor.id === "openrouter-tts" ? (
              <OpenRouterTtsControls
                providerId={descriptor.id}
                recommendedModel={descriptor.recommended_model}
                healthActive={descriptor.active}
              />
            ) : (
              <BrainModelSelector
                providerId={descriptor.id}
                recommendedModel={descriptor.recommended_model}
                healthSection={descriptor.tier}
                healthActive={descriptor.active}
                // An on-device provider's list is what is installed here, so there
                // is nothing to type — and with a single entry, nothing to pick.
                fixedCatalog={Boolean(descriptor.local_runtime)}
              />
            ))}

          {/* TTS/STT model/voice is a single global value, so a configured-but-
              inactive provider can't own it — make the capability discoverable with
              a hint instead of silently hiding the picker. */}
          {(descriptor.tier === "tts" || descriptor.tier === "stt") &&
            descriptor.configured &&
            !descriptor.active && (
              <p className="text-xs text-muted-foreground">
                {t("apikeys_view.model_picker_activate_hint")}
              </p>
            )}

          {/* Realtime needs BOTH a model AND a voice pinned per provider — a
              dedicated compact control (two dropdowns), gated on the card
              already having a stored credential like the other tiers' pickers
              above. */}
          {descriptor.tier === "realtime" &&
            descriptor.configuration_surface !== "live" &&
            (descriptor.configured ||
              // Keep the model/voice pickers mounted through a transient busy
              // probe so the card does not visibly flicker while saying
              // "one moment".
              descriptor.codex_status?.reason_code === "busy") && (
              descriptor.managed_server ? (
                <details className="text-xs text-muted-foreground">
                  <summary className="cursor-pointer">
                    {t("apikeys_view.managed_protocol_options")}
                  </summary>
                  <div className="pt-3">
                    <RealtimeOptionsControl providerId={descriptor.id} healthActive={descriptor.active} />
                  </div>
                </details>
              ) : (
                <RealtimeOptionsControl providerId={descriptor.id} healthActive={descriptor.active} />
              )
            )}

          {/* Footer: the live connectivity test, visually separated from the
              configuration body so "set up" and "verify" read as two steps. */}
          {!hideCredentialControls && <div className="border-t border-border pt-2.5">
            <ProviderTestControl
              providerId={descriptor.id}
              providerLabel={descriptor.label}
              section={descriptor.tier}
              active={descriptor.active}
            />
          </div>}
        </div>
      )}
    </div>
    </>
  );
}
