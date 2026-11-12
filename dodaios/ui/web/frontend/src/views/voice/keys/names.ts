/**
 * A provider's name as a person says it.
 *
 * The catalog labels carry the tier they belong to ("Gemini STT",
 * "Groq: dictation polish") and a note in brackets ("Whisper (on this
 * machine)"). On these screens the group title names the tier and the row's
 * value says where the provider runs, so the label keeps only the name.
 * Presentation only: an unknown shape passes through unchanged.
 */
export function providerName(label: string): string {
  const plain = label
    .replace(/:\s*dictation polish\s*$/i, "")
    .replace(/\s*\([^)]*\)/g, "")
    .replace(/\bSTT\b/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
  return plain || label;
}
