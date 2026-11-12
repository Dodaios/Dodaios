import { useId, useState, type FormEvent, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { DictionaryEntry, DictionaryEntryPayload } from "@/hooks/useDictionary";
import { useT } from "@/i18n";
import { Row } from "@/views/voice/kit";
import { RowFault } from "@/views/voice/shortcuts/RowFault";

/** What the second field holds: the misheard spellings, separated by commas. */
export function parseHeardAs(text: string): string[] {
  return text
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

type Fault = "duplicate" | "save_failed";

/**
 * The editor of one dictionary entry, in place of the row it edits (or at the
 * top of the list for a new one).
 *
 * Two fields, because an entry has two parts: the word, and what it is heard
 * as. The second one may stay empty; the entry is then a plain word to
 * recognise. Enter saves, Escape cancels.
 */
export function EntryEditor({
  entry,
  isTaken,
  onSave,
  onCancel,
}: {
  /** The entry being edited; absent for a new one. */
  entry?: DictionaryEntry;
  /** Whether another entry already holds this word. */
  isTaken: (word: string) => boolean;
  /** Resolves once the entry is stored; a rejection keeps the editor open. */
  onSave: (payload: DictionaryEntryPayload) => Promise<void>;
  onCancel: () => void;
}) {
  const t = useT();
  const wordId = useId();
  const heardAsId = useId();
  const [word, setWord] = useState(entry?.word ?? "");
  const [heardAs, setHeardAs] = useState(entry?.misheard.join(", ") ?? "");
  const [saving, setSaving] = useState(false);
  const [fault, setFault] = useState<Fault | null>(null);

  const cleanWord = word.trim();

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!cleanWord || saving) return;
    if (isTaken(cleanWord)) {
      setFault("duplicate");
      return;
    }
    setSaving(true);
    setFault(null);
    try {
      await onSave({ word: cleanWord, misheard: parseHeardAs(heardAs) });
    } catch {
      // The owner closes the editor on success; on a failure it stays open
      // with what was typed.
      setFault("save_failed");
      setSaving(false);
    }
  }

  function onKeyDown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.stopPropagation();
      onCancel();
    }
  }

  return (
    <form
      onSubmit={(event) => void submit(event)}
      onKeyDown={onKeyDown}
      className="divide-y divide-border"
      data-testid="word-editor"
    >
      <Row
        label={t("voiceui.dictionary.word")}
        htmlFor={wordId}
        below={
          fault && (
            <RowFault testId="word-editor-fault">{t(`voiceui.dictionary.${fault}`)}</RowFault>
          )
        }
      >
        <Input
          id={wordId}
          value={word}
          onChange={(event) => {
            setWord(event.target.value);
            setFault(null);
          }}
          autoFocus
          autoComplete="off"
          spellCheck={false}
          className="h-10 w-64 text-title"
          data-testid="word-field"
        />
      </Row>
      <Row label={t("voiceui.dictionary.heard_as")} htmlFor={heardAsId}>
        <Input
          id={heardAsId}
          value={heardAs}
          onChange={(event) => setHeardAs(event.target.value)}
          autoComplete="off"
          spellCheck={false}
          className="h-10 w-64 text-title"
          data-testid="heard-as-field"
        />
      </Row>
      <div className="flex items-center justify-end gap-row px-block py-3">
        <Button type="button" variant="ghost" onClick={onCancel} disabled={saving} data-testid="word-cancel">
          {t("voiceui.common.cancel")}
        </Button>
        <Button type="submit" disabled={!cleanWord || saving} data-testid="word-save">
          {t("voiceui.common.save")}
        </Button>
      </div>
    </form>
  );
}
