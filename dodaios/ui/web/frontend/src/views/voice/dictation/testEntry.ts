import type { DictationEntry } from "@/hooks/useDictation";

/** A delivered dictation for tests; pass only what a case is about. */
export function testEntry(overrides: Partial<DictationEntry> = {}): DictationEntry {
  return {
    id: "entry-1",
    created_at: new Date(2026, 4, 3, 16, 12).toISOString(),
    raw_text: "Send the report tomorrow.",
    text: "Send the report tomorrow.",
    language: "en",
    duration_s: 3,
    outcome: "inserted",
    method: "paste",
    removed_words: 0,
    cleanup_reason: "",
    word_count: 4,
    discarded: false,
    audio_available: false,
    error: null,
    ...overrides,
  };
}
