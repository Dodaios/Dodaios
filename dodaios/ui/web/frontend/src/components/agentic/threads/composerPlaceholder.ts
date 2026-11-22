import { fill } from "@/i18n";

/**
 * The quiet text in an empty thread composer: one short sentence, then the
 * shortcuts the picked agent really honours ("Ask anything. @ files,
 * / commands" for Claude Code, "@ files, $ skills" for Codex). A shortcut the
 * agent does not know is never offered; an agent with none gets the sentence
 * alone.
 */
const HINTS: readonly (readonly [trigger: string, key: string])[] = [
  ["@", "ide_threads.composer_hint_files"],
  ["$", "ide_threads.composer_hint_skills"],
  ["/", "ide_threads.composer_hint_commands"],
];

export function composerPlaceholder(triggers: readonly string[], t: (key: string) => string): string {
  const hints = HINTS.filter(([trigger]) => triggers.includes(trigger)).map(([, key]) => t(key));
  if (hints.length === 0) return t("ide_threads.composer_placeholder");
  return fill(t("ide_threads.composer_placeholder_hints"), { hints: hints.join(t("ide_threads.composer_hint_separator")) });
}
