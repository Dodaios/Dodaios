/**
 * What a starter or an imported template brings, before anything exists: a
 * name the person can change, the outcome in one line, counted contents
 * (instructions, skills, routines, tools, confirmations), the tools with
 * their state on THIS machine, the optional routine, and the first message
 * the chat will open with. One card for both paths, so a stranger's template
 * is read exactly as carefully as one of ours.
 *
 * Calm on purpose: label and value rows on soft cards, round ticks, plain
 * words for a tool's state, and no decorative icons.
 */
import { useId, useState, type ReactNode } from "react";
import { Check, ChevronDown } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import type { StarterTool, TemplateSummary } from "./startersApi";

export interface PreviewRoutine {
  title: string;
  /** The named schedule slot (`weekday_morning`, …). */
  when: string;
}

interface Props {
  name: string;
  /** The starter's or template's own name: the field starts with it, and an
   *  emptied field falls back to it. */
  defaultName?: string;
  onNameChange: (name: string) => void;
  outcome: string;
  summary: TemplateSummary;
  instructions: string;
  tools: StarterTool[];
  /** Ticked tool ids. */
  picked: ReadonlySet<string>;
  onToggleTool: (id: string) => void;
  routine?: PreviewRoutine | null;
  routineOn?: boolean;
  onRoutineChange?: (on: boolean) => void;
  firstMessage?: string;
  disabled: boolean;
  /** Extra content under the header (an import's source line). */
  note?: ReactNode;
}

function Stat({ label, value, testId }: { label: string; value: string; testId: string }) {
  return (
    <div className="cs-row" data-testid={testId}>
      <span className="cs-row-text">{label}</span>
      <span className="cs-row-end min-w-0 truncate text-right">{value}</span>
    </div>
  );
}

function toolState(tool: StarterTool): "connected" | "not_connected" | "missing" {
  if (tool.connected) return "connected";
  return tool.available ? "not_connected" : "missing";
}

export function TemplatePreviewCard(props: Props) {
  const t = useT();
  const nameId = useId();
  const [showInstructions, setShowInstructions] = useState(false);
  const { summary, tools, picked, routine } = props;
  const pickedCount = tools.filter((tool) => picked.has(tool.id)).length;
  const instructionsValue = summary.instructions_rules > 0
    ? fill(t("agent_create.preview.instructions_rules"), { rules: summary.instructions_rules, words: summary.instructions_words })
    : fill(t("agent_create.preview.instructions_words"), { words: summary.instructions_words });
  const routineCount = routine ? (props.routineOn ? 1 : 0) : summary.routines;

  return (
    <article className="flex flex-col gap-6" data-testid="template-preview">
      <header className="flex min-w-0 flex-col gap-1">
        <h2 className="cs-title truncate text-[20px]" data-testid="template-preview-title">
          {props.name.trim() || props.defaultName || t("agent_create.preview.name_label")}
        </h2>
        <p className="cs-sub text-[14px]">{props.outcome}</p>
        {props.note}
      </header>

      <div className="flex flex-col gap-2">
        <span className="flex items-baseline justify-between gap-2">
          <label htmlFor={nameId} className="cs-label">{t("agent_create.preview.name_label")}</label>
          <span className="cs-hint">{t("agent_create.quick.optional")}</span>
        </span>
        <Input
          id={nameId}
          value={props.name}
          maxLength={40}
          onChange={(event) => props.onNameChange(event.target.value)}
          placeholder={props.defaultName}
          disabled={props.disabled}
          data-testid="template-preview-name"
        />
      </div>

      <section aria-label={t("agent_create.preview.brings")} className="flex flex-col gap-2">
        <h3 className="cs-section-title">{t("agent_create.preview.brings")}</h3>
        <div className="cs-card">
          <Stat label={t("agent_create.preview.instructions")} value={instructionsValue} testId="preview-count-instructions" />
          <Stat label={t("agent_create.preview.skills")}
            value={summary.skills === null ? t("agent_create.preview.skills_all") : String(summary.skills)} testId="preview-count-skills" />
          <Stat label={t("agent_create.preview.routines")} value={String(routineCount)} testId="preview-count-routines" />
          <Stat label={t("agent_create.preview.tools")}
            value={tools.length ? fill(t("agent_create.preview.tools_value"), { picked: pickedCount, total: tools.length }) : "0"} testId="preview-count-tools" />
        </div>
        {summary.asks_before > 0 ? (
          <p className="cs-hint px-1" data-testid="preview-asks-before">
            {fill(t(summary.asks_before === 1 ? "agent_create.preview.asks_before_one" : "agent_create.preview.asks_before_other"), { count: summary.asks_before })}
          </p>
        ) : null}
        {summary.limited_tools ? (
          <p className="cs-hint px-1">{t("agent_create.preview.limited_tools")}</p>
        ) : null}
      </section>

      {tools.length ? (
        <section className="flex flex-col gap-2">
          <h3 className="cs-section-title">{t("agent_create.preview.tools_title")}</h3>
          <ul className="cs-card">
            {tools.map((tool) => {
              const state = toolState(tool);
              const on = picked.has(tool.id);
              return (
                <li key={tool.id}>
                  <label className={cn("cs-row", props.disabled && "cursor-default opacity-60")}>
                    <input
                      type="checkbox"
                      className="peer sr-only"
                      checked={on}
                      disabled={props.disabled}
                      onChange={() => props.onToggleTool(tool.id)}
                      data-testid={`preview-tool-${tool.id}`}
                    />
                    <span className="cs-tick peer-focus-visible:ring-2 peer-focus-visible:ring-ring" data-on={on} aria-hidden>
                      {on ? <Check className="size-3.5" strokeWidth={3} /> : null}
                    </span>
                    <span className="cs-row-text">{tool.label}</span>
                    <span className="cs-row-end" data-tone={state === "not_connected" ? "warn" : undefined}>
                      {t(`agent_create.preview.tool_${state}`)}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
          <p className="cs-hint px-1">{t("agent_create.preview.tools_hint")}</p>
        </section>
      ) : null}

      {routine && props.onRoutineChange ? (
        <section className="cs-card" data-testid="preview-routine">
          <div className="cs-row">
            <div className="min-w-0 flex-1">
              <p className="cs-row-text">{routine.title}</p>
              <p className="cs-hint">
                {t(`agent_create.when.${routine.when}`)} · {t("agent_create.preview.routine_hint")}
              </p>
            </div>
            <Switch
              checked={Boolean(props.routineOn)}
              onCheckedChange={props.onRoutineChange}
              disabled={props.disabled}
              aria-label={t("agent_create.preview.routine_toggle")}
              data-testid="preview-routine-toggle"
            />
          </div>
        </section>
      ) : null}

      {props.firstMessage ? (
        <section className="flex flex-col gap-2">
          <h3 className="cs-section-title">{t("agent_create.preview.first_message")}</h3>
          <p className="cs-card text-[14px] leading-relaxed text-foreground" data-pad="true" data-testid="preview-first-message">
            {props.firstMessage}
          </p>
          <p className="cs-hint px-1">{t("agent_create.preview.first_message_hint")}</p>
        </section>
      ) : null}

      <section className="flex flex-col gap-2 px-1">
        <button
          type="button"
          onClick={() => setShowInstructions((value) => !value)}
          aria-expanded={showInstructions}
          className="cs-link"
        >
          {t("agent_create.preview.read_instructions")}
          <ChevronDown className={cn("size-3.5 transition-transform duration-200 motion-reduce:transition-none", showInstructions && "rotate-180")} aria-hidden />
        </button>
        {showInstructions ? (
          <pre className="cs-card max-h-56 overflow-y-auto whitespace-pre-wrap font-sans text-[14px] leading-relaxed text-foreground-secondary" data-pad="true" data-testid="preview-instructions">
            {props.instructions}
          </pre>
        ) : null}
      </section>
    </article>
  );
}
