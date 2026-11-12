import { Mic } from "lucide-react";

import { SectionTabBar, type SectionTab } from "@/components/layout/SectionTabBar";
import { useStageSection } from "@/components/layout/tiling/tileSection";
import { useLocaleChunk, useT } from "@/i18n";
import { ViewHeader } from "@/views/ChatsView";
import { ApiKeysTab } from "@/views/voice/ApiKeysTab";
import { DictationTab } from "@/views/voice/DictationTab";
import { DictionaryTab } from "@/views/voice/DictionaryTab";
import { LanguageTab } from "@/views/voice/LanguageTab";
import { ShortcutsTab } from "@/views/voice/ShortcutsTab";

/**
 * The Voice section: a title, five tabs, one tab's content.
 *
 * The active sidebar section id is the tab state, so a deep link such as
 * "open the dictionary" lands on its tab without extra routing. The title is
 * the `nav.voice` string, which carries the assistant's name; it is the only
 * heading the section has, and it has no subtitle.
 *
 * The section's strings are the `voice` locale chunk. A tab is not painted
 * before the chunk is resident, so no tab ever shows a raw key.
 */
const TABS = [
  { id: "dictation", labelKey: "nav.dictation" },
  { id: "dictionary", labelKey: "nav.dictionary" },
  { id: "voice-shortcuts", labelKey: "nav.voice_shortcuts" },
  { id: "voice-language", labelKey: "nav.voice_language" },
  { id: "voice-api-keys", labelKey: "nav.voice_api_keys" },
] as const satisfies readonly SectionTab[];

export function VoiceHubView() {
  const t = useT();
  // The tile's own section: in a tiled layout another tile may hold focus.
  const active = useStageSection();
  const ready = useLocaleChunk("voice");

  // The router mounts this view for the five ids above only; anything else
  // falls back to the first tab.
  const current = TABS.some((tab) => tab.id === active) ? active : "dictation";

  return (
    <div className="flex h-full flex-col">
      <ViewHeader icon={<Mic className="h-4 w-4 text-foreground" />} title={t("nav.voice")} />
      <SectionTabBar tabs={TABS} align="center" />
      {/* min-h-0 lets the tab's own scroll container scroll instead of growing
          past the window. */}
      <div className="min-h-0 flex-1 overflow-hidden" data-testid="voice-tab-content">
        {ready && current === "dictation" && <DictationTab />}
        {ready && current === "dictionary" && <DictionaryTab />}
        {ready && current === "voice-shortcuts" && <ShortcutsTab />}
        {ready && current === "voice-language" && <LanguageTab />}
        {ready && current === "voice-api-keys" && <ApiKeysTab />}
      </div>
    </div>
  );
}
