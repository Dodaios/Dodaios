import type { ProviderDescriptor, SectionHealth } from "@/hooks/useProviders";
import type { Verification } from "@/store/providerTests";

/** The one or two words a provider row shows as its value. */
export type RowState =
  | "connected"
  | "key_saved"
  | "set_up"
  | "no_key"
  | "local"
  | "not_installed"
  | "installing"
  | "checking"
  | "not_working";

export interface RowSignals {
  /** What a live check found in this session, if one ran. */
  verification: Verification;
  /** The health record of the tier, when it is about this provider. */
  health?: SectionHealth;
  installing?: boolean;
  checking?: boolean;
}

/**
 * Which state a provider is in.
 *
 * A stored key is "key saved" and nothing more: "connected" is said only after
 * the provider answered a real call. A provider that is ready without a key of
 * its own in any slot (an account set up outside the app) is "set up". A
 * provider that runs on this computer has no key, so its value says where it
 * runs, or that it is not installed.
 */
export function rowState(provider: ProviderDescriptor, signals: RowSignals): RowState {
  if (signals.installing) return "installing";
  if (signals.checking) return "checking";
  const healthStatus = provider.active ? signals.health?.status : undefined;
  if (signals.verification === "failed") return "not_working";
  if (signals.verification !== "ok" && healthStatus === "error") return "not_working";
  if (provider.local_runtime) return provider.local_runtime.ready ? "local" : "not_installed";
  if (provider.auth_mode === "none") return "local";
  if (!provider.configured) return "no_key";
  if (signals.verification === "ok" || healthStatus === "ok") return "connected";
  const slot = provider.secret_keys[0];
  const hasKey =
    !slot || Boolean(provider.secrets_set[slot]) || Boolean(provider.secrets_effective?.[slot]);
  return hasKey ? "key_saved" : "set_up";
}

const FAULTS = new Set([
  "bad_key",
  "no_credits",
  "rate_limited",
  "model_unavailable",
  "unreachable",
  "error",
]);

/** The locale key of the sentence for a failed check; unknown causes read as a plain failure. */
export function faultKey(reason: string | undefined): string {
  return `voiceui.keys.fault.${reason && FAULTS.has(reason) ? reason : "error"}`;
}
