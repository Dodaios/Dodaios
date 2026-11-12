import { useMemo, useState } from "react";
import { Mic } from "lucide-react";

import { localeForUiLanguage } from "@/components/runs/format";
import { Button } from "@/components/ui/button";
import type { DictationEntry, DictationRestoreResult } from "@/hooks/useDictation";
import { useT, useUiLanguage } from "@/i18n";
import { useEventStore } from "@/store/events";
import { Empty, Group, LoadingGroup, SearchField } from "@/views/voice/kit";

import { dayTitle, groupByDay, matching } from "./days";
import { HistoryEntry } from "./HistoryEntry";

/**
 * What was dictated, newest first, one group per calendar day.
 *
 * Above the list: a search over the delivered and the heard text, and "Delete
 * all", which asks once before it empties the history.
 */
export interface HistoryProps {
  entries: readonly DictationEntry[];
  loading: boolean;
  /** A translation or a prompt rewrite is switched on. */
  rewriteChosen: boolean;
  copyEntry: (id: string) => Promise<boolean>;
  discardEntry: (id: string) => Promise<void>;
  restoreEntry: (id: string) => Promise<DictationRestoreResult>;
  deleteEntry: (id: string) => Promise<void>;
  clearHistory: () => Promise<void>;
}

export function History({
  entries,
  loading,
  rewriteChosen,
  copyEntry,
  discardEntry,
  restoreEntry,
  deleteEntry,
  clearHistory,
}: HistoryProps) {
  const t = useT();
  const locale = localeForUiLanguage(useUiLanguage());
  const pushToast = useEventStore((s) => s.pushToast);
  const [query, setQuery] = useState("");
  const [confirmingClear, setConfirmingClear] = useState(false);
  const [clearing, setClearing] = useState(false);

  const days = useMemo(() => groupByDay(matching(entries, query)), [entries, query]);

  /** Runs one request; a failure becomes one plain sentence, not a rejection. */
  async function attempt(request: () => Promise<unknown>) {
    try {
      await request();
    } catch {
      pushToast("error", t("voiceui.dictation.action_failed"));
    }
  }

  async function copy(entry: DictationEntry) {
    const copied = await copyEntry(entry.id).catch(() => false);
    if (!copied) pushToast("error", t("voiceui.dictation.copy_failed"));
    return copied;
  }

  function restore(entry: DictationEntry) {
    return attempt(async () => {
      const result = await restoreEntry(entry.id);
      // The entry is back either way. When its recording was run again and
      // still gave no words, say that instead of letting it pass as restored.
      if (!result.retranscribed && result.detail) {
        pushToast("warning", t("voiceui.dictation.not_transcribed"));
      }
    });
  }

  async function clear() {
    setClearing(true);
    await attempt(clearHistory);
    setClearing(false);
    setConfirmingClear(false);
  }

  if (loading) return <LoadingGroup rows={3} testId="dictation-history-loading" />;

  if (entries.length === 0) {
    return (
      <Empty icon={<Mic aria-hidden="true" />} testId="dictation-history-empty">
        {t("voiceui.dictation.empty")}
      </Empty>
    );
  }

  return (
    <div className="flex flex-col gap-block" data-testid="dictation-history">
      <div className="flex items-center gap-row">
        <SearchField
          value={query}
          onChange={setQuery}
          label={t("voiceui.common.search")}
          className="min-w-0 flex-1"
        />
        {confirmingClear ? (
          <>
            <Button
              type="button"
              variant="ghost"
              disabled={clearing}
              onClick={() => setConfirmingClear(false)}
            >
              {t("voiceui.common.cancel")}
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={clearing}
              onClick={() => void clear()}
              data-testid="dictation-delete-all-confirm"
            >
              {t("voiceui.dictation.delete_all")}
            </Button>
          </>
        ) : (
          <Button
            type="button"
            variant="ghost"
            onClick={() => setConfirmingClear(true)}
            data-testid="dictation-delete-all"
          >
            {t("voiceui.dictation.delete_all")}
          </Button>
        )}
      </div>

      {days.length === 0 ? (
        <Empty testId="dictation-history-no-matches">{t("voiceui.common.no_matches")}</Empty>
      ) : (
        days.map((day) => (
          <Group
            key={day.key}
            title={dayTitle(day.key, locale, {
              today: t("voiceui.dictation.today"),
              yesterday: t("voiceui.dictation.yesterday"),
            })}
          >
            {day.entries.map((entry) => (
              <HistoryEntry
                key={entry.id}
                entry={entry}
                locale={locale}
                rewriteChosen={rewriteChosen}
                onCopy={copy}
                onDiscard={(target) => attempt(() => discardEntry(target.id))}
                onRestore={restore}
                onDelete={(target) => attempt(() => deleteEntry(target.id))}
              />
            ))}
          </Group>
        ))
      )}
    </div>
  );
}
