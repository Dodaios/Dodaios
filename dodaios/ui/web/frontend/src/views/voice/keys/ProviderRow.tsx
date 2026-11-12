import { useEffect, useRef, useState } from "react";
import { Check, KeyRound } from "lucide-react";

import { ProviderLogo } from "@/components/providers/ProviderLogo";
import { Button } from "@/components/ui/button";
import {
  localInstallStatus,
  startLocalInstall,
  switchDictationPolishProvider,
  switchSttProvider,
  testProvider,
  type LocalInstallProgress,
  type ProviderDescriptor,
  type ProviderTestResult,
  type ProviderTier,
  type SectionHealth,
} from "@/hooks/useProviders";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useProviderTestStore, verificationOf } from "@/store/providerTests";
import { KeyField } from "@/views/voice/keys/KeyField";
import { providerName } from "@/views/voice/keys/names";
import { RowNote } from "@/views/voice/keys/RowNote";
import { faultKey, rowState, type RowState } from "@/views/voice/keys/state";
import { IconAction, Row, RowValue } from "@/views/voice/kit";

/** How often a running install is asked for its progress. */
const INSTALL_POLL_MS = 3000;

/** The dot before a state: green once the provider answered, red when it failed. */
const STATE_DOT: Partial<Record<RowState, string>> = {
  connected: "bg-success",
  not_working: "bg-destructive",
};

export interface ProviderRowProps {
  provider: ProviderDescriptor;
  /** Whether another provider of this group is in use; a first key takes over when none is. */
  groupHasActive: boolean;
  /** The group's health record, when it is about this provider. */
  health?: SectionHealth;
  /** Reads the provider list again. */
  onChanged: () => void;
  /** Marks this provider as the one in use before the server confirmed it. */
  onActivateOptimistic: (tier: ProviderTier, id: string) => void;
}

/**
 * One provider: its name, its state, whether it is the one in use, and its key.
 *
 * The key is added, replaced and removed in the row itself. Choosing a
 * provider makes it the one in use. A provider that runs on this computer has
 * no key; it says where it runs, and offers to install itself when it is not
 * there yet.
 */
export function ProviderRow({
  provider,
  groupHasActive,
  health,
  onChanged,
  onActivateOptimistic,
}: ProviderRowProps) {
  const t = useT();
  const name = providerName(provider.label);
  const slot = provider.secret_keys[0] ?? null;
  const stored = slot ? Boolean(provider.secrets_set[slot]) : false;

  const verdict = useProviderTestStore((s) => s.results[provider.id]);
  const recordVerdict = useProviderTestStore((s) => s.record);
  const forgetVerdict = useProviderTestStore((s) => s.forget);

  const [open, setOpen] = useState(false);
  const [activating, setActivating] = useState(false);
  const [checking, setChecking] = useState(false);
  const [fault, setFault] = useState<"switch_failed" | "install_failed" | null>(null);
  const [install, setInstall] = useState<LocalInstallProgress | null>(null);
  const installing = install?.state === "running";

  // The provider-tested event says whether the tested provider is the one in
  // use; the check finishes after the click, so it reads the current value.
  const activeRef = useRef(provider.active);
  activeRef.current = provider.active;
  const onChangedRef = useRef(onChanged);
  onChangedRef.current = onChanged;

  // An install runs for minutes, so the row asks for its progress until it
  // ends, then reads the provider list again.
  useEffect(() => {
    if (!installing) return;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const next = await localInstallStatus(provider.id);
        if (cancelled) return;
        setInstall(next);
        if (next.state === "done" || next.state === "error") {
          window.clearInterval(timer);
          if (next.state === "error") setFault("install_failed");
          onChangedRef.current();
        }
      } catch {
        if (cancelled) return;
        window.clearInterval(timer);
        setInstall(null);
        setFault("install_failed");
      }
    }, INSTALL_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [installing, provider.id]);

  async function startInstall() {
    setFault(null);
    try {
      const started = await startLocalInstall(provider.id);
      setInstall(started);
      if (started.state === "error") setFault("install_failed");
      if (started.state === "done") onChanged();
    } catch {
      setFault("install_failed");
    }
  }

  /** Asks the provider for a real answer and keeps what it said. */
  async function check(announce: boolean) {
    setChecking(true);
    let result: ProviderTestResult;
    try {
      result = await testProvider(provider.id);
    } catch (e) {
      if (!announce) {
        // The check itself broke. That says nothing about the provider.
        setChecking(false);
        return;
      }
      result = {
        provider: provider.id,
        status: "error",
        detail: (e as Error).message,
        latency_ms: 0,
        integration_ok: false,
      };
    }
    recordVerdict(provider.id, result);
    if (announce) {
      window.dispatchEvent(
        new CustomEvent("jarvis:provider-tested", {
          detail: {
            section: provider.tier,
            provider: provider.id,
            provider_label: provider.label,
            active: activeRef.current,
            result,
          },
        }),
      );
    }
    setChecking(false);
    if (result.status !== "ok") onChanged();
  }

  async function activate(assumeConfigured = false) {
    if (provider.active || activating) return;
    if (!assumeConfigured && !provider.configured && slot) {
      // Nothing to switch to yet: open the place where the key goes.
      setOpen(true);
      return;
    }
    setFault(null);
    onActivateOptimistic(provider.tier, provider.id);
    setActivating(true);
    try {
      if (provider.tier === "stt") {
        await switchSttProvider(provider.id);
        window.dispatchEvent(new CustomEvent("jarvis:stt-switched"));
      } else {
        // The setting stores the wording family ("groq"), which is not this
        // row's id ("groq-polish"). An id the chain does not know is ignored
        // without an error, so the family is what has to be sent.
        await switchDictationPolishProvider(provider.polish_family || provider.id);
        window.dispatchEvent(new CustomEvent("jarvis:dictation-polish-switched"));
        // The wording pass hands back the raw text when it fails, so a broken
        // provider looks like a working one. The switch checks itself; the
        // check never blocks the choice.
        void check(false);
      }
      onChanged();
    } catch {
      setFault("switch_failed");
      // Back to the provider that is really in use.
      onChanged();
      window.dispatchEvent(
        new CustomEvent("jarvis:provider-switch-failed", {
          detail: { section: provider.tier, provider: provider.id },
        }),
      );
    } finally {
      setActivating(false);
    }
  }

  function onKeySaved() {
    forgetVerdict(provider.id);
    setFault(null);
    setOpen(false);
    // The first key of a group puts its provider in use.
    if (!groupHasActive && !provider.active) void activate(true);
    // A pasted speech key is checked at once. The wording providers are
    // checked when one is chosen.
    if (provider.tier !== "dictation") void check(true);
  }

  const state = rowState(provider, {
    verification: verificationOf(verdict),
    health,
    installing,
    checking,
  });
  const failure =
    state === "not_working"
      ? faultKey(verificationOf(verdict) === "failed" ? verdict?.status : health?.reason)
      : null;
  const usable = state !== "no_key" && state !== "not_installed" && state !== "installing";
  const dot = STATE_DOT[state];

  const below =
    fault || failure || (open && slot) ? (
      <div className="flex flex-col gap-stack">
        {fault && (
          <RowNote testId={`voice-provider-fault-${provider.id}`}>
            {t(`voiceui.keys.${fault}`)}
          </RowNote>
        )}
        {!fault && failure && (
          <RowNote testId={`voice-provider-fault-${provider.id}`}>{t(failure)}</RowNote>
        )}
        {open && slot && (
          <KeyField
            slot={slot}
            provider={name}
            stored={stored}
            sharedWith={provider.secret_shared_with?.[slot] ?? []}
            onChanged={onChanged}
            onSaved={onKeySaved}
            onRemoved={() => {
              forgetVerdict(provider.id);
              setOpen(false);
            }}
            testId={`voice-provider-key-${provider.id}`}
          />
        )}
      </div>
    ) : undefined;

  return (
    <Row
      label={name}
      icon={<ProviderLogo providerId={provider.id} label={name} />}
      below={below}
      testId={`voice-provider-${provider.id}`}
    >
      <RowValue testId={`voice-provider-state-${provider.id}`}>
        <span className="inline-flex items-center gap-row">
          {dot && <span aria-hidden="true" className={cn("h-2 w-2 rounded-full", dot)} />}
          {t(`voiceui.keys.state.${state}`)}
        </span>
      </RowValue>

      {provider.active ? (
        <span
          role="img"
          aria-label={t("voiceui.keys.in_use")}
          title={t("voiceui.keys.in_use")}
          className="flex h-9 w-9 items-center justify-center text-foreground-strong"
          data-testid={`voice-provider-in-use-${provider.id}`}
        >
          <Check aria-hidden="true" className="h-5 w-5" />
        </span>
      ) : (
        usable && (
          <Button
            variant="outline"
            onClick={() => void activate()}
            disabled={activating}
            aria-label={fill(t("voiceui.keys.use_named"), { provider: name })}
            data-testid={`voice-provider-use-${provider.id}`}
          >
            {t("voiceui.keys.use")}
          </Button>
        )
      )}

      {state === "not_installed" && (
        <Button
          variant="outline"
          onClick={() => void startInstall()}
          aria-label={fill(t("voiceui.keys.install_named"), { provider: name })}
          data-testid={`voice-provider-install-${provider.id}`}
        >
          {t("voiceui.keys.install")}
        </Button>
      )}

      {slot &&
        (state === "no_key" ? (
          <Button
            variant="outline"
            onClick={() => setOpen((current) => !current)}
            aria-expanded={open}
            aria-label={fill(t("voiceui.keys.add_key_named"), { provider: name })}
            data-testid={`voice-provider-edit-${provider.id}`}
          >
            {t("voiceui.keys.add_key")}
          </Button>
        ) : (
          <IconAction
            label={fill(t("voiceui.keys.change_key_named"), { provider: name })}
            onClick={() => setOpen((current) => !current)}
            aria-expanded={open}
            testId={`voice-provider-edit-${provider.id}`}
          >
            <KeyRound aria-hidden="true" />
          </IconAction>
        ))}
    </Row>
  );
}
