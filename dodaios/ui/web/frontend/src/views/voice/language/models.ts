import type { DictationWordingProvider } from "@/hooks/useDictation";
import type { ProviderDescriptor } from "@/hooks/useProviders";
import { providerName } from "@/views/voice/keys/names";

/**
 * Names of the wording models, for the ones that have no entry in the
 * provider list. Brand names, so they are not in the locale files. The list of
 * models itself comes from the server; an id that is not here shows as the id.
 */
const MODEL_NAMES: Record<string, string> = {
  groq: "Groq",
  cerebras: "Cerebras",
  gemini: "Google Gemini",
  openai: "OpenAI",
  openrouter: "OpenRouter",
  ollama: "Ollama",
};

/** The provider-list entry that holds the key of a wording model, if there is one. */
export function modelEntry(
  id: string,
  providers: readonly ProviderDescriptor[],
): ProviderDescriptor | null {
  return (
    providers.find((entry) => entry.tier === "dictation" && entry.polish_family === id) ?? null
  );
}

/** A wording model's name. `served` is the name the server gave it, when it gave one. */
export function modelName(
  id: string,
  providers: readonly ProviderDescriptor[],
  served = "",
): string {
  const known = MODEL_NAMES[id];
  if (known) return known;
  const entry = modelEntry(id, providers);
  if (entry) return providerName(entry.label);
  return served ? providerName(served) : id;
}

/**
 * Whether a wording model runs on this computer.
 *
 * Read from what the server says about it: a model that takes no key is a
 * local one. No model id is named here.
 */
export function modelIsLocal(
  id: string,
  providers: readonly ProviderDescriptor[],
  resolved: DictationWordingProvider | null,
): boolean {
  if (resolved && resolved.family === id) return !resolved.needs_key;
  return modelEntry(id, providers)?.auth_mode === "none";
}
