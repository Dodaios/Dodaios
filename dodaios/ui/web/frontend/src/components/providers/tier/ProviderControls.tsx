import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Copy, Loader2, LogIn, LogOut, PlugZap, Terminal } from "lucide-react";
import { AltCredentialNote } from "@/components/AltCredentialNote";
import { ApiKeyForm } from "@/components/ApiKeyForm";
import { LocalVoicePanel } from "@/components/providers/LocalVoicePanel";
import { Button } from "@/components/ui/button";
import { codexLogout, loginAntigravity, logoutAntigravity, type ProviderDescriptor, type ProviderTestResult, type ProviderTestStatus, type ProviderTier, saveProviderBaseUrl, startCodexLogin, testProvider } from "@/hooks/useProviders";
import { useEventStore } from "@/store/events";
import { useProviderTestStore } from "@/store/providerTests";
import { robustCopy } from "@/lib/clipboard";
import { cn } from "@/lib/utils";
import { useT } from "@/i18n";
import { backendMessage } from "@/lib/backendMessage";
import { LocalRuntimePanel } from "./LocalRuntimePanel";
import { ManagedServerPanel } from "./ManagedServerPanel";
import { OllamaRuntimePanel } from "./OllamaPanels";
import { PROVIDER_STATE_CHIPS, providerStateChip } from "./ProviderChips";

// Tone per status: green = works; amber = reached but key/account/model blocks
// (integration is fine); red = couldn't reach / integration bug. A dot and a
// word — the same vocabulary as the row's state, never a filled capsule.
export const TEST_STATUS_TONE: Record<ProviderTestStatus, { dot: string; text: string }> = {
  ok: { dot: "bg-muted-foreground", text: "text-muted-foreground" },
  not_configured: { dot: "bg-muted-foreground/50", text: "text-muted-foreground" },
  bad_key: { dot: "bg-foreground", text: "text-foreground" },
  no_credits: { dot: "bg-foreground", text: "text-foreground" },
  rate_limited: { dot: "bg-foreground", text: "text-foreground" },
  model_unavailable: { dot: "bg-foreground", text: "text-foreground" },
  unreachable: { dot: "bg-destructive", text: "text-destructive" },
  error: { dot: "bg-destructive", text: "text-destructive" },
};

/**
 * "Test" button + honest result chip. Calls POST /api/providers/{id}/test which
 * makes a REAL minimal call — distinguishing a working provider from an invalid
 * key, an out-of-credits account, or an unreachable endpoint. This is the piece
 * the API-Keys view was missing: the green "configured" badge only ever meant a
 * key STRING was stored, never that the provider answers.
 */
export function ProviderTestControl({
  providerId,
  providerLabel,
  section,
  active,
}: {
  providerId: string;
  providerLabel: string;
  section: ProviderTier;
  active: boolean;
}) {
  const t = useT();
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ProviderTestResult | null>(null);
  const activeRef = useRef(active);
  activeRef.current = active;

  function publish(next: ProviderTestResult) {
    window.dispatchEvent(
      new CustomEvent("jarvis:provider-tested", {
        detail: {
          section,
          provider: providerId,
          provider_label: providerLabel,
          active: activeRef.current,
          result: next,
        },
      }),
    );
  }

  const recordVerdict = useProviderTestStore((s) => s.record);

  async function run() {
    setRunning(true);
    setResult(null);
    try {
      const next = await testProvider(providerId);
      setResult(next);
      recordVerdict(providerId, next);
      publish(next);
    } catch (e) {
      const next: ProviderTestResult = {
        provider: providerId,
        status: "error",
        detail: (e as Error).message,
        latency_ms: 0,
        integration_ok: false,
      };
      setResult(next);
      recordVerdict(providerId, next);
      publish(next);
    } finally {
      setRunning(false);
    }
  }

  const tone = result ? TEST_STATUS_TONE[result.status] : null;
  const note = result
    ? (result.integration_ok
        ? t("apikeys_test.integration_ok_note")
        : t("apikeys_test.integration_bad_note"))
    : "";

  // Footer layout: the action on the left, its last answer on the right —
  // "set up" above the line, "verify" below it.
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <Button
        size="sm"
        variant="ghost"
        onClick={(e) => {
          e.stopPropagation();
          void run();
        }}
        disabled={running}
        className="h-7 gap-1.5 px-2 text-xs text-muted-foreground hover:text-foreground"
      >
        {running ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <PlugZap className="h-3.5 w-3.5" />
        )}
        {running ? t("apikeys_test.running") : t("apikeys_test.button")}
      </Button>

      {result && tone && (
        <span
          data-testid={`provider-test-result-${providerId}`}
          className={cn("inline-flex items-center gap-1.5 text-xs", tone.text)}
          title={[note, result.detail, result.latency_ms ? `${Math.round(result.latency_ms)} ms` : ""]
            .filter(Boolean)
            .join("\n")}
        >
          <span aria-hidden="true" className={cn("h-[7px] w-[7px] rounded-full", tone.dot)} />
          {t(`apikeys_test.status_${result.status}`)}
          {result.status === "ok" && result.latency_ms
            ? ` · ${Math.round(result.latency_ms)} ms`
            : ""}
        </span>
      )}
    </div>
  );
}

/**
 * Radio-button-based active toggle. The source of truth stays
 * `descriptor.active` from `/api/providers` — the radio mirrors server
 * state, it is not held locally. `name="active-{tier}"` gives us browser-
 * native exclusivity per tier (Brain/TTS/STT).
 *
 * `disabled` would suppress onChange; that's why the radio is NOT disabled
 * when a key is missing — instead it routes through `activate()` to raise a
 * warning toast. This way the user gets a reaction to every click, instead
 * of bumping into a silent element.
 */
export function ActiveControl({
  descriptor,
  activating,
  onActivate,
  disabled = false,
  disabledReason,
}: {
  descriptor: ProviderDescriptor;
  activating: boolean;
  onActivate: () => void;
  /**
   * Truly disable the radio (no click, no toast). Used for Codex when it cannot
   * be a brain yet (no OpenAI key) — a click there would be a dead end, so we
   * disable instead of firing a warning toast. Other providers stay clickable
   * (warn-on-click) because their key field is right on the card.
   */
  disabled?: boolean;
  disabledReason?: string;
}) {
  const t = useT();
  const labelTitle = descriptor.active && !descriptor.configured
    ? t("apikeys_view.needs_credentials")
    : descriptor.active
    ? t("apikeys_view.activate_tooltip_active")
    : disabled
      ? disabledReason ?? t("apikeys_view.activate_tooltip_blocked")
      : descriptor.configured
        ? t("apikeys_view.activate_tooltip_activate")
        : descriptor.codex_status?.reason_code
          ? // The reason-specific line names the actual remedy; a generic
            // "connect first" is wrong for most non-ready codex states.
            t(
              (CODEX_STATUS_KEY_BY_REASON as Record<string, string>)[
                descriptor.codex_status.reason_code
              ] ?? "apikeys_view.needs_credentials",
            )
          : t("apikeys_view.needs_credentials");

  // Visually a state word ("In use") or a quiet action ("Use"); semantically
  // still a radio in a per-tier group, so browsers, screen readers and the
  // tests keep the native exclusivity. The native control itself is hidden —
  // the old radio-inside-a-pill read as a 2012 form element.
  return (
    <label
      // The radio owns its own activation; letting the click bubble would run
      // the row handler for the same gesture and toggle the body.
      onClick={(e) => e.stopPropagation()}
      className={cn(
        "inline-flex h-7 shrink-0 select-none items-center gap-2 whitespace-nowrap rounded-control px-2.5 text-xs transition-colors focus-within:ring-2 focus-within:ring-ring",
        disabled ? "cursor-not-allowed" : "cursor-pointer",
        descriptor.active
          ? "font-medium text-foreground"
          : descriptor.configured
            ? "border border-border bg-background text-muted-foreground hover:border-border-strong hover:text-foreground"
            : "border border-dashed border-border text-muted-foreground hover:text-foreground",
      )}
      title={labelTitle}
    >
      <input
        type="radio"
        name={`active-${descriptor.tier}`}
        checked={descriptor.active}
        onChange={() => onActivate()}
        disabled={activating || disabled}
        className="sr-only"
      />
      {descriptor.active && (
        <span
          aria-hidden="true"
          className={cn(
            "h-[7px] w-[7px] rounded-full bg-secondary",
            activating && "animate-pulse motion-reduce:animate-none",
          )}
        />
      )}
      {activating
        ? t("apikeys_view.provider_activating")
        : descriptor.active
          ? descriptor.configured
            ? t("apikeys_view.provider_active")
            : t(PROVIDER_STATE_CHIPS[providerStateChip(descriptor)].key)
          : t("apikeys_view.provider_set_active")}
    </label>
  );
}

export function BaseUrlField({
  descriptor,
  onChanged,
}: {
  descriptor: ProviderDescriptor;
  onChanged: () => void;
}) {
  const t = useT();
  const pushToast = useEventStore((s) => s.pushToast);
  const [value, setValue] = useState(descriptor.base_url ?? "");
  const [saving, setSaving] = useState(false);

  // Follow refetches (e.g. after another card action) without clobbering an
  // in-flight edit: only resync while the user is not mid-save.
  useEffect(() => {
    setValue(descriptor.base_url ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [descriptor.base_url]);

  const dirty = value.trim() !== (descriptor.base_url ?? "");

  async function save() {
    setSaving(true);
    try {
      const stored = await saveProviderBaseUrl(descriptor.id, value.trim() || null);
      setValue(stored ?? "");
      pushToast(
        "success",
        stored ? t("apikeys_base_url.saved") : t("apikeys_base_url.cleared"),
      );
      onChanged();
    } catch (e) {
      pushToast("error", e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-1">
      <label className="text-xs text-muted-foreground">
        {t("apikeys_base_url.label")}
      </label>
      <div className="flex gap-2">
        <input
          type="url"
          aria-label={t("apikeys_base_url.label")}
          data-testid="provider-base-url-input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={
            descriptor.default_base_url ?? t("apikeys_base_url.placeholder_required")
          }
          className="h-8 w-full rounded-md border border-border bg-background px-2 text-xs"
        />
        <Button
          size="sm"
          variant="secondary"
          data-testid="provider-base-url-save"
          onClick={save}
          disabled={saving || !dirty}
        >
          {saving ? t("apikeys_base_url.saving") : t("apikeys_base_url.save")}
        </Button>
      </div>
      <p className="text-xs leading-relaxed text-muted-foreground">
        {descriptor.default_base_url
          ? t("apikeys_base_url.hint_default")
          : t("apikeys_base_url.hint_required")}
      </p>
    </div>
  );
}

export function AuthWidget({
  descriptor,
  onChanged,
  onSavedActivate,
}: {
  descriptor: ProviderDescriptor;
  onChanged: () => void;
  onSavedActivate?: () => void;
}) {
  const t = useT();
  // "Billed through a login, not a key" — the SHAPE that makes the
  // subscription wording true, never a provider id (AP-21).
  const isSubscriptionBilled =
    descriptor.billing === "subscription" && descriptor.secret_keys.length === 0;
  return (
    <div className="space-y-2">
      {/* Billing now reads on the row summary line; the body starts with what
          the user can DO. An experimental route keeps its one-paragraph note,
          as plain text — the violet box said "warning" about a sentence that
          never changes. */}
      {descriptor.experimental && (
        <div
          data-testid={`provider-experimental-note-${descriptor.id}`}
          className="text-xs leading-relaxed text-muted-foreground"
        >
          <p>
            {/* The subscription wording ("uses the ChatGPT plan…") belongs to
                a card that IS billed through a subscription login — the shape,
                never a provider name (AP-21). Bound to `experimental` alone it
                would tell the next experimental provider's users that their
                ChatGPT plan pays for it. */}
            {isSubscriptionBilled ? (
              <>
                <span>{t("apikeys_view.subscription_realtime_description")}</span>{" "}
                <span>{t("apikeys_view.experimental_subscription_fallback")}</span>
              </>
            ) : (
              <span>{t("apikeys_view.experimental_note")}</span>
            )}
          </p>
        </div>
      )}
      <LocalRuntimePanel descriptor={descriptor} onChanged={onChanged} />
      <ManagedServerPanel descriptor={descriptor} onChanged={onChanged} />
      {descriptor.voice_engine && <LocalVoicePanel onChanged={onChanged} />}
      {descriptor.supports_base_url && descriptor.managed_server && (
        <details className="group text-xs">
          <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 text-muted-foreground transition-colors hover:text-foreground [&::-webkit-details-marker]:hidden">
            <ChevronDown
              aria-hidden="true"
              className="h-3 w-3 -rotate-90 transition-transform group-open:rotate-0 motion-reduce:transition-none"
            />
            {t("apikeys_view.managed_advanced_connection")}
          </summary>
          <div className="pt-2">
            <BaseUrlField descriptor={descriptor} onChanged={onChanged} />
          </div>
        </details>
      )}
      {descriptor.supports_base_url && !descriptor.managed_server && (
        <BaseUrlField descriptor={descriptor} onChanged={onChanged} />
      )}
      {/* The card keeps only the runtime line (install / start / running):
          models, roles, the catalogue and Hugging Face live in the Local
          models section, reached through the Open button in the card header.
          LibraryBrowser and LocalModelDownloadPanel stay exported for it. */}
      {descriptor.supports_model_pull && (
        <OllamaRuntimePanel providerId={descriptor.id} onChanged={onChanged} alwaysVisible />
      )}
      {/* Ordered after the server URL on purpose: a download can only be
          offered once the card points at the right server. */}
      {descriptor.auth_mode === "none" && (
        <>
          <p className="text-xs text-muted-foreground">
            {descriptor.secret_keys.length > 0
              ? t("apikeys_view.local_optional_key_hint")
              : t("apikeys_view.local_no_credentials_hint")}
          </p>
          {descriptor.secret_keys.map((k) => (
            <ApiKeyForm
              key={k}
              secretKey={k}
              dashboardUrl={descriptor.dashboard_url}
              configured={Boolean(descriptor.secrets_set[k])}
              effectiveConfigured={Boolean(descriptor.secrets_effective?.[k])}
              coveredNote={descriptor.configuration_surface === "live" ? t("live.shared_key_help") : descriptor.credential_note ?? null}
              coveredEditLabel={descriptor.configuration_surface === "live" ? t("live.manage_key") : undefined}
              sharedWith={descriptor.secret_shared_with?.[k] ?? []}
              credentialHelp={descriptor.credential_help}
              onChanged={onChanged}
              onSavedActivate={onSavedActivate}
            />
          ))}
        </>
      )}
      {descriptor.auth_mode === "codex" && (
        <CodexAuthWidget descriptor={descriptor} onChanged={onChanged} />
      )}
      {descriptor.auth_mode === "antigravity" && (
        <AntigravityAuthWidget descriptor={descriptor} onChanged={onChanged} />
      )}
      {descriptor.auth_mode === "opencode" && (
        <p className="text-xs text-muted-foreground">{t("apikeys_view.opencode_cli_hint")}</p>
      )}
      {descriptor.auth_mode === "api_key" && (
        <>
          {descriptor.secret_keys.map((k) => (
            <ApiKeyForm
              key={k}
              secretKey={k}
              dashboardUrl={descriptor.dashboard_url}
              configured={Boolean(descriptor.secrets_set[k])}
              effectiveConfigured={Boolean(descriptor.secrets_effective?.[k])}
              coveredNote={descriptor.configuration_surface === "live" ? t("live.shared_key_help") : descriptor.credential_note ?? null}
              coveredEditLabel={descriptor.configuration_surface === "live" ? t("live.manage_key") : undefined}
              sharedWith={descriptor.secret_shared_with?.[k] ?? []}
              credentialHelp={descriptor.credential_help}
              // A pasted key is checked right away — the dictation polish
              // family owns its own probe, so it keeps the manual Test button.
              testAfterSave={
                descriptor.tier === "dictation"
                  ? undefined
                  : {
                      id: descriptor.id,
                      label: descriptor.label,
                      section: descriptor.tier,
                      active: descriptor.active,
                    }
              }
              onChanged={onChanged}
              onSavedActivate={onSavedActivate}
            />
          ))}
          {descriptor.alt_credential && (
            <AltCredentialNote alt={descriptor.alt_credential} />
          )}
        </>
      )}
    </div>
  );
}

// Exhaustive by construction: adding a value to CodexStatus["reason_code"]
// without a card mapping fails the TypeScript build here instead of silently
// falling through to a wrong status line (the BUG-008 multi-layer enum class).
export const CODEX_STATUS_KEY_BY_REASON: Record<
  NonNullable<NonNullable<ProviderDescriptor["codex_status"]>["reason_code"]>,
  string
> = {
  ready: "apikeys_codex.status_ready",
  login_required: "apikeys_codex.status_login_required",
  login_in_progress: "apikeys_codex.status_login_in_progress",
  lifecycle_unavailable: "apikeys_codex.status_lifecycle_unavailable",
  not_installed: "apikeys_codex.status_not_installed",
  setup_invalid: "apikeys_codex.status_setup_invalid",
  plan_unsupported: "apikeys_codex.status_plan_unsupported",
  busy: "apikeys_codex.status_busy",
};

// States in which the install row and an active Connect button would be
// wrong: transient windows, a login the user must FINISH (not restart), and
// an OS the feature does not support at all.
export const CODEX_NO_INSTALL_PROMPT_REASONS = new Set<string>([
  "busy",
  "login_in_progress",
  "lifecycle_unavailable",
]);

export function CodexAuthWidget({
  descriptor,
  onChanged,
}: {
  descriptor: ProviderDescriptor;
  onChanged: () => void;
}) {
  const t = useT();
  const [pending, setPending] = useState<"login" | "logout" | "copy" | null>(null);
  const [loginPolling, setLoginPolling] = useState(false);
  const pushToast = useEventStore((s) => s.pushToast);
  const status = descriptor.codex_status;
  const installCommand = descriptor.install_hint ?? "npm i -g @openai/codex";
  const subscriptionOnly = descriptor.secret_keys.length === 0;
  const loginReady = Boolean(
    status?.connected && (!subscriptionOnly || status.mode === "chatgpt"),
  );
  const codexStatusMessage =
    status && typeof status.message === "string"
      ? backendMessage(
          t,
          "apikeys_codex.status_msg",
          status.message_code,
          status.message_params,
          status.message,
        )
      : undefined;
  const subscriptionStatusKey = !status
    ? "apikeys_codex.status_loading"
    : status.reason_code && status.reason_code !== "login_required"
      ? // Runtime fallback for a backend value the union does not know yet —
        // the Record enforces exhaustiveness at compile time, but a newer
        // backend must not render t(undefined).
        ((CODEX_STATUS_KEY_BY_REASON as Record<string, string>)[
          status.reason_code
        ] ?? "apikeys_codex.status_loading")
      : !status.installed
        ? "apikeys_codex.status_not_installed"
        : "apikeys_codex.status_login_required";

  useEffect(() => {
    if (!loginPolling) return;
    if (loginReady) {
      // The login just landed. `/api/providers` alone does not refresh call
      // readiness: realtime AVAILABILITY lives on the voice-mode snapshot,
      // which listens for this event. Without it the card went green while the
      // call surfaces still said no voice provider was ready — for up to five
      // minutes, and on a long-open window indefinitely.
      window.dispatchEvent(new CustomEvent("jarvis:realtime-switched"));
      return;
    }
    let stopped = false;
    const deadline = Date.now() + 5 * 60_000;
    let timer: number | null = null;

    const poll = () => {
      if (stopped) return;
      onChanged();
      if (Date.now() < deadline) {
        timer = window.setTimeout(poll, 5_000);
      } else {
        setLoginPolling(false);
      }
    };
    timer = window.setTimeout(poll, 1_000);
    return () => {
      stopped = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [loginPolling, loginReady, onChanged]);

  async function handleCopy() {
    setPending("copy");
    try {
      const copied = await robustCopy(installCommand);
      pushToast(
        copied ? "success" : "warning",
        copied ? t("apikeys_codex.install_command_copied") : installCommand,
      );
    } finally {
      setPending(null);
    }
  }

  async function handleLogin() {
    setPending("login");
    try {
      await startCodexLogin(subscriptionOnly);
      pushToast("info", t("apikeys_codex.login_started"));
      // OAuth has no fixed completion time. Keep polling until the parent sees
      // connected truth instead of leaving a successful slow login invisible.
      onChanged();
      setLoginPolling(true);
    } catch (e) {
      pushToast("error", (e as Error).message);
    } finally {
      setPending(null);
    }
  }

  async function handleLogout() {
    setPending("logout");
    setLoginPolling(false);
    try {
      await codexLogout(subscriptionOnly);
      pushToast("info", t("apikeys_codex.disconnected"));
      onChanged();
      // Losing the login removes a realtime provider: the call surfaces have to
      // re-read availability, or they keep offering a call that cannot start.
      window.dispatchEvent(new CustomEvent("jarvis:realtime-switched"));
    } catch (e) {
      pushToast("error", (e as Error).message);
    } finally {
      setPending(null);
    }
  }

  // Connected: collapse to a small "logged in" badge instead of the full card.
  // No connect button (no second invitation), no API-key field (the key lives on
  // the separate "OpenAI" provider). Activation as the worker happens in the
  // Subagent list below.
  if (loginReady && status) {
    return (
      <div className="space-y-3">
        <div
          data-testid="codex-connected"
          className="flex flex-wrap items-center gap-2 rounded-md border border-muted-foreground/30 bg-muted-foreground/[0.06] px-3 py-2 text-xs"
        >
          <Check className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span className="min-w-0 break-words text-foreground">
            {subscriptionOnly
              ? t("apikeys_codex.connected_chatgpt")
              : codexStatusMessage ?? t("apikeys_codex.connected_chatgpt")}
          </span>
          {status.version && (
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono">{status.version}</code>
          )}
          {status.mode === "chatgpt" && <span className="chip-yellow">CHATGPT-LOGIN</span>}
          <Button
            size="sm"
            variant="ghost"
            onClick={handleLogout}
            disabled={pending !== null}
            className="ml-auto"
          >
            <LogOut className="h-3.5 w-3.5" />
            {t("apikeys_codex.disconnect")}
          </Button>
        </div>
      </div>
    );
  }

  // Not connected: status + (install hint) + the single "connect" action.
  return (
    <div className="space-y-3">
      <div className="rounded-md border border-border bg-background p-3 text-xs text-muted-foreground">
        <div className="flex flex-wrap items-center gap-2">
          <span>
            {subscriptionOnly
              ? t(subscriptionStatusKey)
              : codexStatusMessage ?? t("apikeys_codex.status_loading")}
          </span>
          {status?.version && (
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono">{status.version}</code>
          )}
        </div>
        {/* A real setup problem carries a precise backend diagnosis (for
            example the exact required Codex version). Hiding it behind the
            generic sentence left users guessing what to fix. */}
        {subscriptionOnly &&
          (status?.reason_code === "setup_invalid" ||
            status?.reason_code === "not_installed" ||
            status?.reason_code === "plan_unsupported" ||
            status?.reason_code === "lifecycle_unavailable") &&
          status.message && (
            <div
              data-testid="codex-setup-detail"
              className="mt-2 break-words border-t border-border pt-2 font-mono text-xs"
            >
              <span className="mr-1 font-sans">
                {t("apikeys_codex.setup_detail_label")}
              </span>
              {status.message}
            </div>
          )}
      </div>

      {/* Deliberately `codex_status.installed`, NOT the payload's
          `cli_installed`. The backend's carve-out for an ownership window
          (answer "is it installed" from PATH instead of the owned profile)
          protects exactly the states this row already suppresses below, so
          reading both would add a second source of truth that can disagree —
          and the two DO disagree in practice. See useProviders.ts. */}
      {!status?.installed &&
        !CODEX_NO_INSTALL_PROMPT_REASONS.has(status?.reason_code ?? "") && (
        <div className="flex flex-wrap items-center gap-2">
          <code className="min-w-[220px] flex-1 rounded-md border border-border bg-muted px-3 py-1.5 font-mono text-xs">
            {installCommand}
          </code>
          <Button size="sm" variant="outline" onClick={handleCopy} disabled={pending === "copy"}>
            {pending === "copy" ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            {t("apikeys_codex.copy_command")}
          </Button>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          onClick={handleLogin}
          disabled={
            pending !== null ||
            loginPolling ||
            // Finish the RUNNING login instead of starting a second one; an
            // unsupported OS can never connect at all.
            status?.reason_code === "login_in_progress" ||
            status?.reason_code === "lifecycle_unavailable" ||
            (!status?.installed && status?.reason_code !== "busy")
          }
          title={
            status?.reason_code === "login_in_progress"
              ? t("apikeys_codex.status_login_in_progress")
              : status?.reason_code === "lifecycle_unavailable"
                ? t("apikeys_codex.status_lifecycle_unavailable")
                : undefined
          }
        >
          <LogIn className="h-3.5 w-3.5" />
          {t("apikeys_codex.connect_chatgpt")}
        </Button>
        <Button size="sm" variant="outline" asChild>
          <a href="https://help.openai.com/en/articles/11381614" target="_blank" rel="noreferrer">
            <Terminal className="h-3.5 w-3.5" />
            {t("apikeys_codex.install_codex")}
          </a>
        </Button>
        {/* A plan-refused or invalid profile is stored but unusable — offer
            the in-app exit the backend implements, even though the connected
            panel (with its Disconnect) never renders in these states. */}
        {(status?.reason_code === "plan_unsupported" ||
          status?.reason_code === "setup_invalid") && (
          <Button
            size="sm"
            variant="ghost"
            onClick={handleLogout}
            disabled={pending !== null}
          >
            <LogOut className="h-3.5 w-3.5" />
            {t("apikeys_codex.disconnect")}
          </Button>
        )}
      </div>

    </div>
  );
}

export function AntigravityAuthWidget({
  descriptor,
  onChanged,
}: {
  descriptor: ProviderDescriptor;
  onChanged: () => void;
}) {
  const t = useT();
  const [pending, setPending] = useState<"login" | "logout" | "copy" | null>(null);
  const pushToast = useEventStore((s) => s.pushToast);
  const status = descriptor.antigravity_status;
  const antigravityStatusMessage =
    status && typeof status.message === "string"
      ? backendMessage(
          t,
          "apikeys_antigravity.status_msg",
          status.message_code,
          status.message_params,
          status.message,
        )
      : undefined;
  const installCommand =
    descriptor.install_hint ?? "curl -fsSL https://antigravity.google/cli/install.sh | bash";

  async function handleCopy() {
    setPending("copy");
    try {
      const copied = await robustCopy(installCommand);
      pushToast(copied ? "success" : "warning", copied ? t("apikeys_codex.install_command_copied") : installCommand);
    } finally {
      setPending(null);
    }
  }

  async function handleLogin() {
    setPending("login");
    try {
      await loginAntigravity();
      pushToast("info", t("apikeys_antigravity.login_started"));
      // The Google CLI opens the browser "Sign in with Google" flow; it only
      // completes once the user clicks through (seconds later). Poll a few times
      // so the card flips to the compact "connected" state on its own once the
      // on-disk creds appear — no manual refresh needed (mirror of Codex).
      [1500, 4000, 8000, 15000, 25000].forEach((ms) =>
        window.setTimeout(onChanged, ms),
      );
    } catch (e) {
      pushToast("error", (e as Error).message);
    } finally {
      setPending(null);
    }
  }

  async function handleLogout() {
    setPending("logout");
    try {
      await logoutAntigravity();
      pushToast("info", t("apikeys_antigravity.disconnected"));
      onChanged();
    } catch (e) {
      pushToast("error", (e as Error).message);
    } finally {
      setPending(null);
    }
  }

  // Connected: collapse to a small "logged in" badge instead of the full card.
  // The Google subscription bills the brain/subagent; no key field (OAuth-only).
  if (status?.connected) {
    return (
      <div className="space-y-3">
        <div
          data-testid="antigravity-connected"
          className="flex flex-wrap items-center gap-2 rounded-md border border-muted-foreground/30 bg-muted-foreground/[0.06] px-3 py-2 text-xs"
        >
          <Check className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span className="min-w-0 break-words text-foreground">
            {status.user_email
              ? t("apikeys_antigravity.connected_as").replace("{0}", status.user_email)
              : antigravityStatusMessage || t("apikeys_antigravity.connected")}
          </span>
          {status.version && (
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono">{status.version}</code>
          )}
          <span className="chip-yellow">GOOGLE-LOGIN</span>
          <Button
            size="sm"
            variant="ghost"
            onClick={handleLogout}
            disabled={pending !== null}
            className="ml-auto"
          >
            <LogOut className="h-3.5 w-3.5" />
            {t("apikeys_codex.disconnect")}
          </Button>
        </div>
      </div>
    );
  }

  // Not connected: status + (install hint) + the single "connect" action.
  return (
    <div className="space-y-3">
      <div className="rounded-md border border-border bg-background p-3 text-xs text-muted-foreground">
        <div className="flex flex-wrap items-center gap-2">
          <span>{antigravityStatusMessage ?? t("apikeys_antigravity.status_loading")}</span>
          {status?.version && (
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono">{status.version}</code>
          )}
        </div>
      </div>

      {!status?.installed && (
        <div className="flex flex-wrap items-center gap-2">
          <code className="min-w-[220px] flex-1 rounded-md border border-border bg-muted px-3 py-1.5 font-mono text-xs">
            {installCommand}
          </code>
          <Button size="sm" variant="outline" onClick={handleCopy} disabled={pending === "copy"}>
            {pending === "copy" ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            {t("apikeys_codex.copy_command")}
          </Button>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={handleLogin} disabled={pending !== null || !status?.installed}>
          <LogIn className="h-3.5 w-3.5" />
          {t("apikeys_antigravity.connect_google")}
        </Button>
        <Button size="sm" variant="outline" asChild>
          <a href="https://antigravity.google" target="_blank" rel="noreferrer">
            <Terminal className="h-3.5 w-3.5" />
            {t("apikeys_antigravity.install_antigravity")}
          </a>
        </Button>
      </div>
    </div>
  );
}
