import { useMemo, useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  useDictionary,
  type DictionaryEntry,
  type DictionaryEntryPayload,
} from "@/hooks/useDictionary";
import { useT } from "@/i18n";
import { EntryEditor } from "@/views/voice/dictionary/EntryEditor";
import {
  Empty,
  Group,
  IconAction,
  LoadingGroup,
  Notice,
  Row,
  SearchField,
  VoicePage,
} from "@/views/voice/kit";

/** Which entry the editor is open for: a new one, or an existing one by id. */
type Editing = { kind: "new" } | { kind: "entry"; id: string } | null;

function sameWord(a: string, b: string): boolean {
  return a.trim().toLowerCase() === b.trim().toLowerCase();
}

/**
 * An entry on one line: the word, then what it is misheard as.
 *
 * The word comes first so that a long list of mishearings is what gets cut
 * off at the end of the row, never the word itself.
 */
function EntryLabel({ entry }: { entry: DictionaryEntry }) {
  if (entry.misheard.length === 0) return <>{entry.word}</>;
  return (
    <>
      {entry.word}{" "}
      <span className="ml-2 font-normal text-muted-foreground">{entry.misheard.join(", ")}</span>
    </>
  );
}

/**
 * The Dictionary tab: the person's own words for speech recognition.
 *
 * A list in alphabetical order, a search field and one Add action. An entry is
 * a word to recognise, or a correction (what is heard, and the word it should
 * be). Adding and editing happen in the list itself, in the place of the row.
 * A new or changed entry applies to the next thing said; nothing restarts.
 */
export function DictionaryTab() {
  const t = useT();
  const { entries, loading, error, refetch, createEntry, updateEntry, removeEntry } =
    useDictionary();

  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<Editing>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteFailed, setDeleteFailed] = useState(false);
  // The hook clears its error the moment it loads again, and an empty list
  // without an error would read as "no words yet" for the length of the request.
  const [retrying, setRetrying] = useState(false);

  const sorted = useMemo(
    () => [...entries].sort((a, b) => a.word.localeCompare(b.word, undefined, { sensitivity: "base" })),
    [entries],
  );

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return sorted;
    // The entry being edited stays in the list whatever is typed into the
    // search field, so its editor cannot disappear with unsaved text in it.
    const editedId = editing?.kind === "entry" ? editing.id : null;
    return sorted.filter(
      (entry) =>
        entry.id === editedId ||
        entry.word.toLowerCase().includes(needle) ||
        entry.misheard.some((variant) => variant.toLowerCase().includes(needle)),
    );
  }, [sorted, query, editing]);

  function startAdding() {
    // A new word may not match what is being searched for, and would then
    // vanish the moment it is saved.
    setQuery("");
    setDeleteFailed(false);
    setEditing({ kind: "new" });
  }

  function startEditing(entry: DictionaryEntry) {
    setDeleteFailed(false);
    setEditing({ kind: "entry", id: entry.id });
  }

  async function save(payload: DictionaryEntryPayload) {
    if (editing?.kind === "entry") await updateEntry(editing.id, payload);
    else await createEntry(payload);
    setEditing(null);
  }

  async function remove(entry: DictionaryEntry) {
    setDeleteFailed(false);
    setDeletingId(entry.id);
    try {
      await removeEntry(entry.id);
    } catch {
      setDeleteFailed(true);
    } finally {
      setDeletingId(null);
    }
  }

  async function retry() {
    setRetrying(true);
    try {
      await refetch();
    } finally {
      setRetrying(false);
    }
  }

  const addButton = (
    <Button onClick={startAdding} disabled={editing?.kind === "new"} data-testid="word-add">
      <Plus aria-hidden="true" />
      {t("voiceui.common.add")}
    </Button>
  );

  if (loading || retrying) {
    return (
      <VoicePage testId="voice-dictionary">
        <LoadingGroup rows={4} testId="words-loading" />
      </VoicePage>
    );
  }

  if (error && entries.length === 0) {
    return (
      <VoicePage testId="voice-dictionary">
        <Notice
          tone="fault"
          testId="words-load-failed"
          action={
            <Button variant="outline" onClick={() => void retry()} data-testid="words-retry">
              {t("voiceui.common.retry")}
            </Button>
          }
        >
          {t("voiceui.dictionary.load_failed")}
        </Notice>
      </VoicePage>
    );
  }

  if (entries.length === 0 && editing === null) {
    return (
      <VoicePage testId="voice-dictionary">
        <Empty testId="words-empty" action={addButton}>
          {t("voiceui.dictionary.empty")}
        </Empty>
      </VoicePage>
    );
  }

  const adding = editing?.kind === "new";

  return (
    <VoicePage testId="voice-dictionary">
      {entries.length > 0 && (
        <div className="flex items-center gap-stack">
          <SearchField
            value={query}
            onChange={setQuery}
            label={t("voiceui.common.search")}
            testId="word-search"
            className="min-w-0 flex-1"
          />
          {addButton}
        </div>
      )}

      {deleteFailed && (
        <Notice tone="fault" testId="words-delete-failed">
          {t("voiceui.dictionary.delete_failed")}
        </Notice>
      )}

      {visible.length === 0 && !adding ? (
        <Empty testId="words-no-results">{t("voiceui.common.no_matches")}</Empty>
      ) : (
        <Group testId="words">
          {adding && (
            <EntryEditor
              isTaken={(word) => entries.some((entry) => sameWord(entry.word, word))}
              onSave={save}
              onCancel={() => setEditing(null)}
            />
          )}
          {visible.map((entry) =>
            editing?.kind === "entry" && editing.id === entry.id ? (
              <EntryEditor
                key={entry.id}
                entry={entry}
                isTaken={(word) =>
                  entries.some((other) => other.id !== entry.id && sameWord(other.word, word))
                }
                onSave={save}
                onCancel={() => setEditing(null)}
              />
            ) : (
              <Row key={entry.id} label={<EntryLabel entry={entry} />} testId={`word-row-${entry.id}`}>
                <IconAction
                  label={t("voiceui.common.edit")}
                  testId={`word-edit-${entry.id}`}
                  onClick={() => startEditing(entry)}
                >
                  <Pencil aria-hidden="true" />
                </IconAction>
                <IconAction
                  label={t("voiceui.common.delete")}
                  testId={`word-delete-${entry.id}`}
                  disabled={deletingId === entry.id}
                  onClick={() => void remove(entry)}
                >
                  <Trash2 aria-hidden="true" />
                </IconAction>
              </Row>
            ),
          )}
        </Group>
      )}
    </VoicePage>
  );
}
