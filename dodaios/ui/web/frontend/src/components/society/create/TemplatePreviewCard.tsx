/**
 * What a starter or an imported template brings, before anything exists: a
 * name the person can change, the outcome in one line, counted contents
 * (instructions, skills, routines, tools, confirmations), the tools with
 * their state on THIS machine, the optional routine, and the first message
 * the chat will open with. One card for both paths, so a stranger's template
 * is read exactly as carefully as one of ours.
 */
import { useId, useState, type ReactNode } from "react";
import { BookText, Check, ChevronDown, Clock, Repeat, ShieldCheck, Sparkles, Wrench } from "lucide-react";
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
  icon: ReactNode;
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

function Stat({ icon, label, value, testId }: { icon: ReactNode; label: string; value: string; testId: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 rounded-[10px] border border-border bg-background/60 px-3 py-2.5" data-testid={testId}>
      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span className="text-foreground-faint [&>svg]:size-3.5" aria-hidden>{icon}</span>
        {label}
      </span>
      <span className="truncate text-sm font-medium text-foreground-strong">{value}</span>
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
    <article className="flex flex-col gap-5" data-testid="template-preview">
      <header className="flex items-start gap-3">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-[12px] border border-border bg-secondary text-foreground [&>svg]:size-5" aria-hidden>
          {props.icon}
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h2 className="truncate text-lg font-semibold text-foreground-strong" data-testid="template-preview-title">
            {props.name.trim() || props.defaultName || t("agent_create.preview.name_label")}
          </h2>
          <p className="text-sm text-foreground-secondary">{props.outcome}</p>
          {props.note}
        </div>
      </header>

      <div className="flex flex-col gap-1.5 text-sm">
        <span className="flex items-baseline justify-between gap-2">
          <label htmlFor={nameId} className="font-medium">{t("agent_create.preview.name_label")}</label>
          <span className="text-xs text-foreground-faint">{t("agent_create.quick.optional")}</span>
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
        <h3 className="text-xs font-medium uppercase tracking-[0.08em] text-muted-foreground">{t("agent_create.preview.brings")}</h3>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat icon={<BookText />} label={t("agent_create.preview.instructions")} value={instructionsValue} testId="preview-count-instructions" />
          <Stat icon={<Sparkles />} label={t("agent_create.preview.skills")}
            value={summary.skills === null ? t("agent_create.preview.skills_all") : String(summary.skills)} testId="preview-count-skills" />
          <Stat icon={<Repeat />} label={t("agent_create.preview.routines")} value={String(routineCount)} testId="preview-count-routines" />
          <Stat icon={<Wrench />} label={t("agent_create.preview.tools")}
            value={tools.length ? fill(t("agent_create.preview.tools_value"), { picked: pickedCount, total: tools.length }) : "0"} testId="preview-count-tools" />
        </div>
        {summary.asks_before > 0 ? (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground" data-testid="preview-asks-before">
            <ShieldCheck className="size-3.5 text-success" aria-hidden />
            {fill(t(summary.asks_before === 1 ? "agent_create.preview.asks_before_one" : "agent_create.preview.asks_before_other"), { count: summary.asks_before })}
          </p>
        ) : null}
        {summary.limited_tools ? (
          <p className="text-xs text-muted-foreground">{t("agent_create.preview.limited_tools")}</p>
        ) : null}
      </section>

      {tools.length ? (
        <section className="flex flex-col gap-2">
          <div className="flex items-baseline justify-between gap-2">
            <h3 className="text-xs font-medium uppercase tracking-[0.08em] text-muted-foreground">{t("agent_create.preview.tools_title")}</h3>
            <span className="text-xs text-foreground-faint">{t("agent_create.preview.tools_hint")}</span>
          </div>
          <ul className="flex flex-col divide-y divide-border overflow-hidden rounded-[10px] border border-border">
            {tools.map((tool) => {
              const state = toolState(tool);
              const on = picked.has(tool.id);
              return (
                <li key={tool.id}>
                  <label className={cn(
                    "flex cursor-pointer items-center gap-3 px-3 py-2 text-sm transition-colors hover:bg-secondary/50",
                    props.disabled && "cursor-default opacity-60",
                  )}>
                    <input
                      type="checkbox"
                      className="peer sr-only"
                      checked={on}
                      disabled={props.disabled}
                      onChange={() => props.onToggleTool(tool.id)}
                      data-testid={`preview-tool-${tool.id}`}
                    />
                    <span className={cn(
                      "flex size-4 shrink-0 items-center justify-center rounded-[4px] border transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-ring",
                      on ? "border-foreground bg-foreground text-background" : "border-border-strong bg-transparent",
                    )} aria-hidden>
                      {on ? <Check className="size-3" strokeWidth={3} /> : null}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-foreground">{tool.label}</span>
                    <span className={cn(
                      "shrink-0 rounded-full px-2 py-0.5 text-xs",
                      state === "connected" && "bg-success/10 text-success",
                      state === "not_connected" && "bg-warning/10 text-warning",
                      state === "missing" && "bg-secondary text-muted-foreground",
                    )}>
                      {t(`agent_create.preview.tool_${state}`)}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {routine && props.onRoutineChange ? (
        <section className="flex items-start gap-3 rounded-[10px] border border-border px-3 py-3" data-testid="preview-routine">
          <Clock className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="text-sm text-foreground">{routine.title}</p>
            <p className="text-xs text-muted-foreground">
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
        </section>
      ) : null}

      <section className="flex flex-col gap-2">
        <button
          type="button"
          onClick={() => setShowInstructions((value) => !value)}
          aria-expanded={showInstructions}
          className="flex items-center gap-1.5 self-start rounded text-xs font-medium uppercase tracking-[0.08em] text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {t("agent_create.preview.read_instructions")}
          <ChevronDown className={cn("size-3.5 transition-transform duration-200 motion-reduce:transition-none", showInstructions && "rotate-180")} aria-hidden />
        </button>
        {showInstructions ? (
          <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded-[10px] border border-border bg-background/60 px-3 py-2.5 font-sans text-sm text-foreground-secondary" data-testid="preview-instructions">
            {props.instructions}
          </pre>
        ) : null}
      </section>

      {props.firstMessage ? (
        <section className="flex flex-col gap-1.5">
          <h3 className="text-xs font-medium uppercase tracking-[0.08em] text-muted-foreground">{t("agent_create.preview.first_message")}</h3>
          <p className="rounded-[10px] border border-dashed border-border-strong px-3 py-2.5 text-sm text-foreground" data-testid="preview-first-message">
            {props.firstMessage}
          </p>
          <p className="text-xs text-foreground-faint">{t("agent_create.preview.first_message_hint")}</p>
        </section>
      ) : null}
    </article>
  );
}
