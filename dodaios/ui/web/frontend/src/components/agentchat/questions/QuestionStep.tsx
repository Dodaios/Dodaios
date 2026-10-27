import { forwardRef, useId, useState } from "react";
import { ChevronDown } from "lucide-react";
import { useT } from "@/i18n";
import type { QuestionItem } from "../reduce";
import { OptionRow, OwnAnswerRow } from "./OptionRow";
import { LETTERS, type LocalAnswer } from "./questionModel";

/**
 * One question of the card: its prompt as the title, the lettered answers,
 * and the person's own-words row behind the next letter. Every step of a
 * series is drawn at once and stacked in one grid cell (QuestionCard), so
 * only `active` is visible and the card keeps the height of its tallest step
 * (the review step alone sizes to itself, and the frame eases between them).
 */
export const QuestionStep = forwardRef<HTMLTextAreaElement, {
  item: QuestionItem;
  local: LocalAnswer;
  active: boolean;
  locked: boolean;
  titleId?: string;
  onPick: (index: number) => void;
  onText: (text: string) => void;
  onSubmitText: () => void;
}>(function QuestionStep({ item, local, active, locked, titleId, onPick, onText, onSubmitText }, ref) {
  const t = useT();
  const [why, setWhy] = useState(false);
  const reasonId = useId();
  const multi = item.kind === "multi";
  const help = multi ? t("question_card.pick_many") : item.kind === "text" ? t("question_card.write_answer") : "";
  const ownLetter = item.kind === "text" && !item.options.length ? null : LETTERS[item.options.length] ?? null;
  return (
    <div className="qc-step" data-active={active ? "" : undefined} aria-hidden={active ? undefined : true}
      // An inactive step keeps its height but must not take focus or clicks.
      {...(active ? {} : ({ inert: "" } as Record<string, string>))}>
      <h3 id={titleId} className="qc-title">{item.question}</h3>
      {help ? <p className="qc-help">{help}</p> : null}
      <div className="qc-list" role="group" aria-label={item.question}>
        {item.options.map((option, index) => (
          <OptionRow
            key={`${index}:${option.label}`}
            letter={LETTERS[index]}
            option={option}
            multi={multi}
            selected={local.picks.includes(index)}
            recommended={index < item.recommendedCount}
            disabled={locked}
            onPick={() => onPick(index)}
          />
        ))}
        {item.allowCustom ? (
          <OwnAnswerRow
            ref={ref}
            letter={ownLetter}
            value={local.text}
            disabled={locked}
            placeholder={item.kind === "text" ? t("question_card.text_placeholder") : t("question_card.something_else")}
            onChange={onText}
            onSubmit={onSubmitText}
          />
        ) : null}
      </div>
      {item.recommendationReason && item.options.length ? (
        <>
          <button type="button" className="qc-why" aria-expanded={why} aria-controls={reasonId} onClick={() => setWhy((open) => !open)}>
            <span>{t("question_card.why_toggle")}</span>
            <ChevronDown aria-hidden className="qc-chevron h-3 w-3" style={why ? { transform: "rotate(180deg)" } : undefined} />
          </button>
          <div className="qc-collapse" data-open={why ? "" : undefined} id={reasonId}>
            <div>
              <p className="qc-reason">{item.recommendationReason}</p>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
});
