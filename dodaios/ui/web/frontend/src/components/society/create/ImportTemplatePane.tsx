/**
 * Bring an agent somebody shared: paste its template or open the file. The
 * backend checks it against the same stranger-safety rules the marketplace
 * uses (`agent_template.validate_template`) and counts what it brings, and
 * nothing is created until the person has read the preview and pressed
 * Create.
 */
import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import "../calmSheet.css";
import { Textarea } from "@/components/ui/textarea";
import { useT } from "@/i18n";
import { readFileText } from "@/lib/agentShare";
import { parseTemplateText, previewTemplate, type TemplatePreview } from "./startersApi";

export interface ImportState {
  template: Record<string, unknown> | null;
  preview: TemplatePreview | null;
  /** The text changed and its check is still running: the preview on screen
   *  is the previous text's, so nothing may be created from it yet. */
  pending: boolean;
}

export const EMPTY_IMPORT: ImportState = { template: null, preview: null, pending: false };

interface Props {
  text: string;
  onTextChange: (text: string) => void;
  onChange: (state: ImportState) => void;
  disabled: boolean;
}

/** Wait this long after the last keystroke before asking the backend. */
const CHECK_DELAY_MS = 350;

export function ImportTemplatePane({ text, onTextChange, onChange, disabled }: Props) {
  const t = useT();
  const fileInput = useRef<HTMLInputElement>(null);
  const [checking, setChecking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const last = useRef<ImportState>(EMPTY_IMPORT);
  const emit = (state: ImportState) => { last.current = state; onChangeRef.current(state); };
  // useT hands out a new function every render; the check runs on text only.
  const tRef = useRef(t);
  tRef.current = t;

  useEffect(() => {
    const trimmed = text.trim();
    setErrors([]);
    if (!trimmed) {
      setProblem(null);
      emit(EMPTY_IMPORT);
      return;
    }
    const template = parseTemplateText(trimmed);
    if (!template) {
      setProblem(tRef.current("agent_create.import.invalid_json"));
      emit(EMPTY_IMPORT);
      return;
    }
    setProblem(null);
    // Keep the last preview on screen while this text is checked, but hold Create.
    emit({ ...last.current, pending: true });
    let live = true;
    const timer = window.setTimeout(() => {
      setChecking(true);
      previewTemplate(template)
        .then((preview) => {
          if (!live) return;
          setErrors(preview.ok ? [] : preview.errors);
          emit({ template, preview: preview.ok ? preview : null, pending: false });
        })
        .catch((exc: unknown) => {
          if (!live) return;
          setProblem(exc instanceof Error ? exc.message : String(exc));
          emit(EMPTY_IMPORT);
        })
        .finally(() => { if (live) setChecking(false); });
    }, CHECK_DELAY_MS);
    return () => { live = false; window.clearTimeout(timer); };
    // `emit` only writes through refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  async function openFile(file: File | undefined) {
    if (!file) return;
    try {
      onTextChange(await readFileText(file));
    } catch (exc) {
      setProblem(exc instanceof Error ? exc.message : String(exc));
    }
  }

  return (
    <div className="flex flex-col gap-3" data-testid="import-pane">
      <div className="flex items-center justify-between gap-2">
        <label htmlFor="agent-import-text" className="cs-label">{t("agent_create.import.paste_label")}</label>
        <button
          type="button"
          onClick={() => fileInput.current?.click()}
          disabled={disabled}
          className="cs-btn"
          data-variant="soft"
          data-size="sm"
          data-testid="import-open-file"
        >
          {t("agent_create.import.open_file")}
        </button>
        <input
          ref={fileInput}
          type="file"
          accept=".json,application/json"
          className="hidden"
          onChange={(event) => { void openFile(event.target.files?.[0]); event.target.value = ""; }}
          data-testid="import-file-input"
        />
      </div>
      <Textarea
        id="agent-import-text"
        value={text}
        onChange={(event) => onTextChange(event.target.value)}
        placeholder={t("agent_create.import.paste_placeholder")}
        disabled={disabled}
        spellCheck={false}
        className="min-h-[180px] font-mono text-[13px]"
        data-testid="import-text"
      />
      {checking ? (
        <p className="cs-hint flex items-center gap-2" role="status">
          <Loader2 className="size-3.5 animate-spin" aria-hidden /> {t("agent_create.import.checking")}
        </p>
      ) : null}
      {problem ? <p role="alert" className="cs-hint" data-tone="error">{problem}</p> : null}
      {errors.length ? (
        <div role="alert" className="cs-card gap-1.5 bg-destructive/5" data-pad="true" data-testid="import-errors">
          <p className="cs-label text-destructive">{t("agent_create.import.errors_title")}</p>
          <ul className="cs-hint list-disc pl-5">
            {errors.map((error) => <li key={error}>{error}</li>)}
          </ul>
        </div>
      ) : null}
      {!text.trim() ? (
        <p className="cs-hint">{t("agent_create.import.safety_note")}</p>
      ) : null}
    </div>
  );
}
