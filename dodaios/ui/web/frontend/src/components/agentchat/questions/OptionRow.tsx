import { forwardRef, useLayoutEffect, useRef, type KeyboardEvent } from "react";
import { PenLine } from "lucide-react";
import { useT } from "@/i18n";
import type { QuestionOption } from "../reduce";
import { KeyCap } from "./KeyCap";

/** One prepared answer: a lettered row, toggled for a multi-select question. */
export function OptionRow({
  letter,
  option,
  selected,
  multi,
  recommended,
  disabled,
  onPick,
}: {
  letter: string;
  option: QuestionOption;
  selected: boolean;
  multi: boolean;
  recommended: boolean;
  disabled: boolean;
  onPick: () => void;
}) {
  const t = useT();
  return (
    <button
      type="button"
      data-qc-row=""
      data-recommended={recommended ? "true" : "false"}
      data-described={option.description ? "" : undefined}
      aria-pressed={multi ? selected : undefined}
      aria-keyshortcuts={letter}
      disabled={disabled}
      onClick={onPick}
      className="qc-row"
    >
      <KeyCap on={selected}>{letter}</KeyCap>
      <span className="qc-row-body">
        <span className="qc-label">{option.label}</span>
        {option.description ? <span className="qc-desc">{option.description}</span> : null}
      </span>
      {recommended ? <span className="qc-tag">{t("question_card.recommended")}</span> : null}
    </button>
  );
}

/**
 * The person's own words: an auto-growing field behind the next letter.
 * Enter sends it, Shift+Enter starts a new line, Escape leaves the field.
 */
export const OwnAnswerRow = forwardRef<HTMLTextAreaElement, {
  letter: string | null;
  value: string;
  placeholder: string;
  disabled: boolean;
  onChange: (text: string) => void;
  onSubmit: () => void;
}>(function OwnAnswerRow({ letter, value, placeholder, disabled, onChange, onSubmit }, ref) {
  const t = useT();
  const local = useRef<HTMLTextAreaElement | null>(null);
  // Browsers without `field-sizing: content` grow the field by hand.
  useLayoutEffect(() => {
    const el = local.current;
    if (!el || (typeof CSS !== "undefined" && CSS.supports?.("field-sizing", "content"))) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      onSubmit();
    } else if (event.key === "Escape") {
      event.currentTarget.blur();
    }
  };
  return (
    <label className="qc-own" data-qc-own="">
      <KeyCap on={Boolean(value.trim())}>{letter ?? <PenLine className="h-3 w-3" />}</KeyCap>
      <textarea
        ref={(el) => {
          local.current = el;
          if (typeof ref === "function") ref(el);
          else if (ref) ref.current = el;
        }}
        rows={1}
        value={value}
        disabled={disabled}
        maxLength={2000}
        placeholder={placeholder}
        aria-label={t("question_card.own_answer")}
        aria-keyshortcuts={letter ?? undefined}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
      />
    </label>
  );
});
