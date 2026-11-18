import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode, type TextareaHTMLAttributes } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { ChevronDown, ChevronRight, Sparkles, X, Zap, type LucideIcon } from "lucide-react";

import { ChatMarkdown } from "@/components/agentchat/ChatMarkdown";
import { REPLY_PROSE } from "@/components/agentchat/LeadReply";
import { FOCUS, PANEL_ICON } from "@/components/home/panelParts";
import { useRunLocale } from "@/components/runs/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { fill, useT } from "@/i18n";
import { NEUTRAL_ASSISTANT_NAME } from "@/lib/assistantNameCache";
import {
  clockOf,
  gathersAhead,
  useCreateRitual,
  usePrepareRitual,
  useRemoveRitual,
  useRitual,
  useRituals,
  useRunRitual,
  useUpdateRitual,
  type Ritual,
  type RitualDraft,
  type RitualLimits,
  type RitualStepCall,
  type RitualStepDraft,
  type RitualTodayText,
  type RitualWhen,
} from "@/lib/ritualsApi";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { TextAction } from "@/views/assistant/Section";

/** How long "Delete for good" waits for its second click before it is "Delete" again. */
const DISARM_MS = 5_000;

/** A phrase ends at a comma, so several can be typed or pasted in one go. */
const PHRASE_END = /[,，]/;

const HINT = "mt-1.5 text-sm text-muted-foreground";

/** A step's line in the dialog. `id` is the server's; a line the person just added has none. */
interface Row {
  key: string;
  id: string;
  text: string;
  /** The sentence as it was read from the server; "" for a line the person added. */
  loaded: string;
  /** The one tool call the sentence came with. It belongs to that sentence only. */
  call?: RitualStepCall;
}

/** The dialog's fields as the person sees them. */
interface Form {
  name: string;
  enabled: boolean;
  phrases: string[];
  /** What is typed into the phrase field and not yet a phrase of its own. */
  phrase: string;
  /** "Only at certain times": the window and the days count. */
  timed: boolean;
  from: string;
  to: string;
  weekdays: number[];
  once: boolean;
  now: Row[];
  ahead: Row[];
  prepareFrom: string;
}

/** How many lines were added so far, so that each one gets a key of its own. */
let addedRows = 0;

/** An empty line for a step that is still to be written. */
function emptyRow(): Row {
  addedRows += 1;
  return { key: `new-${addedRows}`, id: "", text: "", loaded: "" };
}

/**
 * The tool call a line still has: the one it was read with, for as long as
 * its sentence is the one it was read with. A reworded sentence may ask for
 * something else, so the call does not go with it.
 */
function callOf(row: Row): RitualStepCall | undefined {
  return row.call && row.text.trim() === row.loaded ? row.call : undefined;
}

/** A call in a few plain words: what the server says it does, else the tool's name. */
function callWords(call: RitualStepCall): string {
  return call.says?.trim() || call.tool;
}

/** The fields of a ritual as it is saved; a new one starts with one line to write into. */
function formOf(ritual: Ritual | null): Form {
  const rows = (when: RitualWhen): Row[] =>
    (ritual?.steps ?? []).filter((step) => step.when === when)
      .map((step) => ({ key: step.id, id: step.id, text: step.text, loaded: step.text.trim(), call: step.call }));
  return {
    name: ritual?.name ?? "",
    enabled: ritual?.enabled ?? true,
    phrases: ritual?.phrases ?? [],
    phrase: "",
    timed: Boolean(ritual && (ritual.window_from || ritual.window_to || ritual.weekdays.length > 0)),
    from: ritual?.window_from ?? "",
    to: ritual?.window_to ?? "",
    weekdays: ritual?.weekdays ?? [],
    once: ritual?.once_per_day ?? true,
    now: ritual ? rows("now") : [emptyRow()],
    ahead: rows("ahead"),
    prepareFrom: ritual?.prepare_from ?? "",
  };
}

/** `phrases` with what was typed: trimmed, one per comma, none twice whatever its case, no more than `max`. */
function withPhrases(phrases: readonly string[], typed: string, max: number | undefined): string[] {
  const all = [...phrases];
  for (const part of typed.split(PHRASE_END)) {
    const text = part.trim().replace(/\s+/g, " ");
    if (!text || (max !== undefined && all.length >= max)) continue;
    if (!all.some((phrase) => phrase.toLocaleLowerCase() === text.toLocaleLowerCase())) all.push(text);
  }
  return all;
}

/** What the fields say, as the server takes it. */
function draftOf(form: Form, maxPhrases: number | undefined): RitualDraft {
  const steps = (rows: Row[], when: RitualWhen): RitualStepDraft[] =>
    rows.flatMap((row) => {
      const text = row.text.trim();
      // A line left empty is no step. One that is only reworded keeps its id, so it stays the same step.
      if (!text) return [];
      const step: RitualStepDraft = row.id ? { id: row.id, when, text } : { when, text };
      // Its tool call goes back as it came, unless the sentence it belongs to was reworded.
      const call = callOf(row);
      if (call) step.call = call;
      return [step];
    });
  const ahead = steps(form.ahead, "ahead");
  return {
    name: form.name.trim(),
    // A phrase still in the field counts: nobody has to press Enter before Save.
    phrases: withPhrases(form.phrases, form.phrase, maxPhrases),
    steps: [...steps(form.now, "now"), ...ahead],
    enabled: form.enabled,
    // "Always" keeps neither the window nor the days.
    window_from: form.timed ? form.from : "",
    window_to: form.timed ? form.to : "",
    weekdays: form.timed ? [...form.weekdays].sort((a, b) => a - b) : [],
    once_per_day: form.once,
    prepare_from: ahead.length > 0 ? form.prepareFrom : "",
  };
}

/** The seven days as the person's language shortens them, Monday first. */
function weekdayNames(locale: string): { short: string; long: string }[] {
  const short = new Intl.DateTimeFormat(locale, { weekday: "short" });
  const long = new Intl.DateTimeFormat(locale, { weekday: "long" });
  // 1 January 2024 was a Monday.
  return Array.from({ length: 7 }, (_, index) => {
    const day = new Date(2024, 0, 1 + index);
    return { short: short.format(day), long: long.format(day) };
  });
}

/** Today's line of a ritual: where the gathering stands, and when the ritual ran. */
function todayWords(today: RitualTodayText | null, t: (key: string) => string): { gathered: string; failed: boolean; ran: string } {
  if (!today) return { gathered: "", failed: false, ran: "" };
  const failed = today.prep_state === "failed";
  const gathered =
    today.prep_state === "running" ? t("rituals.gathering")
    : failed ? (today.prep_error ? fill(t("rituals.gather_failed"), { reason: today.prep_error }) : t("rituals.state_failed"))
    : today.prep_state === "ready" && today.prepared_ms !== null ? fill(t("rituals.gathered_at"), { time: clockOf(today.prepared_ms) })
    : "";
  const ran = today.fired_ms !== null ? fill(t("rituals.ran_at"), { time: clockOf(today.fired_ms) }) : "";
  return { gathered, failed, ran };
}

/** A titled part of the dialog: a quiet label over its rows, like a part of the assistant's panel. */
function Part({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-label={title} data-testid={`ritual-${id}`} className="mt-5">
      <h3 className="pb-1.5 text-sm text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

/** The phrases that start the ritual: each one a small chip that can be taken away, and a field that adds one. */
function Phrases({ phrases, typed, max, maxChars, onChange }: {
  phrases: string[];
  /** What is in the field and not a phrase yet. */
  typed: string;
  max: number | undefined;
  maxChars: number | undefined;
  onChange: (phrases: string[], typed: string) => void;
}) {
  const t = useT();
  const full = max !== undefined && phrases.length >= max;

  const type = (value: string) => {
    const parts = value.split(PHRASE_END);
    const rest = parts.pop() ?? "";
    if (parts.length === 0) {
      onChange(phrases, value);
      return;
    }
    // Everything before the last comma is a phrase; what follows it is still being typed.
    const next = withPhrases(phrases, parts.join(","), max);
    onChange(next, max !== undefined && next.length >= max ? "" : rest.trimStart());
  };
  const take = () => {
    if (typed.trim()) onChange(withPhrases(phrases, typed, max), "");
  };

  return (
    <>
      <div className="flex flex-wrap items-center gap-1.5">
        {phrases.map((phrase, index) => (
          <span key={phrase} data-testid="ritual-phrase"
            className="inline-flex h-8 max-w-full items-center gap-1 rounded-md bg-secondary pl-2.5 pr-1 text-sm text-foreground">
            <span className="min-w-0 truncate">{phrase}</span>
            <button type="button" aria-label={fill(t("rituals.phrase_remove"), { phrase })}
              onClick={() => onChange(phrases.filter((_, at) => at !== index), typed)}
              className={cn("shrink-0 rounded-sm p-0.5 text-muted-foreground transition-colors hover:text-foreground", FOCUS)}>
              <X aria-hidden strokeWidth={1.75} className="h-3.5 w-3.5" />
            </button>
          </span>
        ))}
        {!full && (
          <Input data-testid="ritual-phrase-input" aria-label={t("rituals.phrase_add")} placeholder={t("rituals.phrase_add")}
            value={typed} maxLength={maxChars} className="h-8 min-w-40 flex-1"
            onChange={(event) => type(event.target.value)}
            onKeyDown={(event) => {
              // Enter that only settles a word of an input method is not the end of a phrase.
              if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
              event.preventDefault();
              take();
            }}
            onBlur={take} />
        )}
      </div>
      <p className={HINT}>{t("rituals.phrases_hint")}</p>
    </>
  );
}

/**
 * A step's sentence, shown whole: the field looks like the one-line field and
 * grows with what is written, so a long sentence is never cut at the edge.
 * A step is one sentence, so Enter adds no line.
 */
function Sentence({ value, className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { value: string }) {
  const field = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const element = field.current;
    // Without a layout (a test's document) there is no height to follow.
    if (!element || element.scrollHeight === 0) return;
    element.style.height = "auto";
    // The border counts: the field's height includes it, its scroll height does not.
    element.style.height = `${element.scrollHeight + element.offsetHeight - element.clientHeight}px`;
  }, [value]);

  return (
    <textarea ref={field} rows={1} value={value}
      onKeyDown={(event) => { if (event.key === "Enter") event.preventDefault(); }}
      className={cn(
        "block min-h-9 w-full resize-none overflow-hidden rounded-md border border-border-strong bg-input px-3 py-1.5 text-base leading-snug text-foreground",
        "placeholder:text-foreground-faint",
        "transition-colors focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        className,
      )}
      {...props} />
  );
}

/** The words of the two kinds of step: what happens the moment the phrase is said, and what is gathered before. */
const STEP_WORDS: Record<RitualWhen, { add: string; label: string; remove: string; placeholder: string }> = {
  now: { add: "rituals.now_add", label: "rituals.now_step", remove: "rituals.now_remove", placeholder: "rituals.now_placeholder" },
  ahead: { add: "rituals.ahead_add", label: "rituals.ahead_step", remove: "rituals.ahead_remove", placeholder: "rituals.ahead_placeholder" },
};

/** The steps of one kind: a line each, rewritten in place, and a quiet button that adds one. */
function Steps({ when, icon: Icon, rows, focusKey, canAdd, maxChars, onChange, onAdd }: {
  when: RitualWhen;
  icon: LucideIcon;
  rows: Row[];
  /** The line that was just added: it takes the cursor. */
  focusKey: string | null;
  canAdd: boolean;
  maxChars: number | undefined;
  onChange: (rows: Row[]) => void;
  onAdd: () => void;
}) {
  const t = useT();
  const words = STEP_WORDS[when];
  return (
    <>
      {rows.map((row, index) => {
        // Only a step for the moment can come down to one tool call.
        const call = when === "now" ? callOf(row) : undefined;
        return (
          <div key={row.key} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-x-2.5 pb-1.5">
            <Icon aria-hidden strokeWidth={1.75} className={cn(PANEL_ICON, "mt-2.5")} />
            <Sentence data-testid={`ritual-${when}-${index}`} aria-label={fill(t(words.label), { n: index + 1 })}
              placeholder={t(words.placeholder)} value={row.text} maxLength={maxChars} autoFocus={row.key === focusKey}
              onChange={(event) => onChange(rows.map((other) => (other.key === row.key ? { ...other, text: event.target.value.replace(/\s*\n\s*/g, " ") } : other)))} />
            <button type="button" data-testid={`ritual-${when}-remove-${index}`} aria-label={fill(t(words.remove), { n: index + 1 })}
              onClick={() => onChange(rows.filter((other) => other.key !== row.key))}
              className={cn("mt-1 shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground", FOCUS)}>
              <X aria-hidden strokeWidth={1.75} className="h-4 w-4" />
            </button>
            {/* What the sentence comes down to, under it: this step needs no model and is done without a wait. */}
            {call && (
              <p data-testid={`ritual-${when}-call-${index}`} title={t("rituals.call_hint")}
                className="col-start-2 mt-1 flex min-w-0 items-center gap-1.5 text-sm text-muted-foreground">
                <Zap aria-hidden strokeWidth={1.75} className="h-3 w-3 shrink-0" />
                <span className="min-w-0 truncate">{callWords(call)}</span>
              </p>
            )}
          </div>
        );
      })}
      {canAdd && <TextAction data-testid={`ritual-${when}-add`} onClick={onAdd}>{t(words.add)}</TextAction>}
    </>
  );
}

/** What was gathered for the ritual today, folded away until it is asked for. */
function Gathered({ text }: { text: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <div className="mt-5">
      <button type="button" data-testid="ritual-gathered" aria-expanded={open} onClick={() => setOpen((value) => !value)}
        className={cn("inline-flex items-center gap-1.5 rounded-sm text-sm text-muted-foreground transition-colors hover:text-foreground", FOCUS)}>
        <Icon aria-hidden strokeWidth={1.75} className="h-4 w-4 shrink-0" />
        {t("rituals.gathered_title")}
      </button>
      {open && (
        <div data-testid="ritual-gathered-text" className={cn(REPLY_PROSE, "mt-2")}>
          <ChatMarkdown text={text} />
        </div>
      )}
    </div>
  );
}

/**
 * Removes the ritual in two clicks, without a second dialog on top of this
 * one: the first click only arms the button, and an armed button nobody
 * presses falls back by itself.
 */
function DeleteButton({ disabled, onDelete }: { disabled: boolean; onDelete: () => void }) {
  const t = useT();
  const [armed, setArmed] = useState(false);

  useEffect(() => {
    if (!armed) return;
    const timer = setTimeout(() => setArmed(false), DISARM_MS);
    return () => clearTimeout(timer);
  }, [armed]);

  return (
    <TextAction data-testid="ritual-delete" data-armed={armed || undefined} disabled={disabled}
      onClick={() => (armed ? onDelete() : setArmed(true))}
      className={cn(armed && "text-destructive hover:text-destructive focus-visible:text-destructive")}>
      {t(armed ? "rituals.delete_confirm" : "rituals.delete")}
    </TextAction>
  );
}

function RitualForm({ ritual, today, limits, onClose }: {
  /** The ritual as it is saved; null for one that is being written. */
  ritual: Ritual | null;
  today: RitualTodayText | null;
  limits: RitualLimits | undefined;
  onClose: () => void;
}) {
  const t = useT();
  const locale = useRunLocale();
  const assistantName = useEventStore((s) => s.assistantName);
  const create = useCreateRitual();
  const update = useUpdateRitual();
  const remove = useRemoveRitual();
  const run = useRunRitual();
  const prepare = usePrepareRitual();
  const [form, setForm] = useState(() => formOf(ritual));
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const [refusal, setRefusal] = useState("");
  const seeded = useRef(ritual);
  const touched = useRef(false);

  // The dialog opens on the list's copy of the ritual. Its own copy takes
  // over when it arrives, as long as the person has not written anything.
  useEffect(() => {
    if (seeded.current === ritual || touched.current) return;
    seeded.current = ritual;
    setForm(formOf(ritual));
  }, [ritual]);

  const change = (fields: Partial<Form>) => {
    touched.current = true;
    setForm((current) => ({ ...current, ...fields }));
  };

  const days = useMemo(() => weekdayNames(locale), [locale]);
  const maxPhrases = limits?.max_phrases;
  const draft = draftOf(form, maxPhrases);
  const saved = useMemo(() => (ritual ? JSON.stringify(draftOf(formOf(ritual), maxPhrases)) : null), [ritual, maxPhrases]);
  // Run and gather act on the ritual as it is saved, so they wait for a save.
  const dirty = saved !== null && JSON.stringify(draft) !== saved;
  const complete = draft.name !== "" && draft.phrases.length > 0 && draft.steps.length > 0;
  const busy = create.isPending || update.isPending || remove.isPending || run.isPending || prepare.isPending;
  const canAddStep = !limits || form.now.length + form.ahead.length < limits.max_steps;
  const canGather = ritual !== null && gathersAhead(ritual);
  const words = todayWords(today, t);
  const saveFirst = dirty ? t("rituals.save_first") : undefined;
  // The name the person gave the assistant; the product's name while there is none.
  const ownName = assistantName.trim();
  const name = ownName && ownName !== NEUTRAL_ASSISTANT_NAME ? ownName : t("sidebar.conversation");

  const refused = (error: Error) => setRefusal(error.message);

  const save = () => {
    if (!complete || busy) return;
    setRefusal("");
    if (ritual) update.mutate({ id: ritual.id, patch: draft }, { onSuccess: onClose, onError: refused });
    else create.mutate(draft, { onSuccess: onClose, onError: refused });
  };

  const start = (id: string, title: string) => {
    setRefusal("");
    run.mutate(id, {
      onSuccess: () => {
        useEventStore.getState().pushToast("success", fill(t("rituals.started"), { title }));
        onClose();
      },
      onError: refused,
    });
  };

  const gather = (id: string) => {
    setRefusal("");
    prepare.mutate(id, { onError: refused });
  };

  const erase = (id: string) => {
    setRefusal("");
    remove.mutate(id, { onSuccess: onClose, onError: refused });
  };

  const addRow = (when: RitualWhen) => {
    const row = emptyRow();
    setFocusKey(row.key);
    change(when === "now" ? { now: [...form.now, row] } : { ahead: [...form.ahead, row] });
  };

  return (
    <>
      {/* A ritual with many steps is taller than the dialog: its fields scroll, and the buttons under
          them stay where they are. The part that scrolls reaches to the dialog's edges and keeps the
          inset inside, so no focus ring is cut at its border. */}
      <div data-testid="ritual-fields" className="-mx-4 -mt-4 min-h-0 flex-1 overflow-y-auto px-4 pb-2 pt-4">
        <div className="flex items-center gap-3">
          <Input data-testid="ritual-name" aria-label={t("rituals.name_label")} placeholder={t("rituals.name_placeholder")}
            value={form.name} maxLength={limits?.max_name_chars} onChange={(event) => change({ name: event.target.value })} />
          <Switch data-testid="ritual-enabled" aria-label={t("rituals.enabled")} checked={form.enabled}
            onCheckedChange={(enabled) => change({ enabled })} />
        </div>

        {ritual && (words.gathered || words.ran || canGather) && (
          <div className="mt-2 flex items-baseline justify-between gap-4">
            <p data-testid="ritual-status" role="status" className="min-w-0 flex-1 text-sm text-muted-foreground">
              {words.gathered && <span className={words.failed ? "text-destructive" : undefined}>{words.gathered}</span>}
              {words.gathered && words.ran ? " · " : ""}
              {words.ran}
            </p>
            {canGather && (
              // A button that is off takes no pointer, so the reason also sits on the span around it.
              <span title={saveFirst} className="shrink-0">
                <TextAction data-testid="ritual-gather" title={saveFirst} onClick={() => gather(ritual.id)}
                  disabled={dirty || busy || today?.prep_state === "running"}>
                  {t("rituals.gather_now")}
                </TextAction>
              </span>
            )}
          </div>
        )}

        <Part id="phrases" title={t("rituals.phrases_title")}>
          <Phrases phrases={form.phrases} typed={form.phrase} max={maxPhrases} maxChars={limits?.max_phrase_chars}
            onChange={(phrases, phrase) => change({ phrases, phrase })} />
        </Part>

        <Part id="when" title={t("rituals.when_title")}>
          <div className="flex flex-wrap items-center gap-1">
            {[false, true].map((timed) => (
              <button key={String(timed)} type="button" aria-pressed={form.timed === timed}
                data-testid={timed ? "ritual-when-timed" : "ritual-when-always"} onClick={() => change({ timed })}
                className={cn("rounded-md px-2.5 py-1 text-sm font-medium transition-colors", FOCUS,
                  form.timed === timed ? "bg-secondary text-foreground-strong" : "text-muted-foreground hover:text-foreground")}>
                {t(timed ? "rituals.when_timed" : "rituals.when_always")}
              </button>
            ))}
          </div>
          {form.timed && (
            <>
              <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted-foreground">
                <label className="flex items-center gap-2">
                  {t("rituals.window_from")}
                  <Input type="time" data-testid="ritual-from" className="w-28" value={form.from}
                    onChange={(event) => change({ from: event.target.value })} />
                </label>
                <label className="flex items-center gap-2">
                  {t("rituals.window_to")}
                  <Input type="time" data-testid="ritual-to" className="w-28" value={form.to}
                    onChange={(event) => change({ to: event.target.value })} />
                </label>
              </div>
              <div role="group" aria-label={t("rituals.days_label")} className="mt-2.5 flex flex-wrap items-center gap-1">
                {days.map((day, index) => {
                  const on = form.weekdays.includes(index);
                  return (
                    <button key={day.long} type="button" aria-pressed={on} aria-label={day.long} title={day.long}
                      data-testid={`ritual-day-${index}`}
                      onClick={() => change({ weekdays: on ? form.weekdays.filter((other) => other !== index) : [...form.weekdays, index] })}
                      className={cn("h-8 min-w-10 rounded-md px-2 text-sm transition-colors", FOCUS,
                        on ? "bg-secondary text-foreground-strong" : "text-muted-foreground hover:text-foreground")}>
                      {day.short}
                    </button>
                  );
                })}
              </div>
              <p className={HINT}>{t("rituals.days_hint")}</p>
            </>
          )}
          <label className="mt-2.5 flex items-center justify-between gap-4">
            <span className="text-sm text-foreground">{t("rituals.once_per_day")}</span>
            <Switch data-testid="ritual-once" checked={form.once} onCheckedChange={(once) => change({ once })} />
          </label>
        </Part>

        <Part id="now" title={t("rituals.now_title")}>
          <Steps when="now" icon={Zap} rows={form.now} focusKey={focusKey} canAdd={canAddStep} maxChars={limits?.max_step_chars}
            onChange={(now) => change({ now })} onAdd={() => addRow("now")} />
          <p className={HINT}>{fill(t("rituals.now_hint"), { assistant: name })}</p>
        </Part>

        <Part id="ahead" title={t("rituals.ahead_title")}>
          <Steps when="ahead" icon={Sparkles} rows={form.ahead} focusKey={focusKey} canAdd={canAddStep} maxChars={limits?.max_step_chars}
            onChange={(ahead) => change({ ahead })} onAdd={() => addRow("ahead")} />
          <p className={HINT}>{t("rituals.ahead_hint")}</p>
          {form.ahead.length > 0 && (
            <>
              <label className="mt-2.5 flex items-center gap-2 text-sm text-foreground">
                {t("rituals.prepare_from")}
                <Input type="time" data-testid="ritual-prepare-from" className="w-28" value={form.prepareFrom}
                  onChange={(event) => change({ prepareFrom: event.target.value })} />
              </label>
              <p className={HINT}>{t("rituals.prepare_from_hint")}</p>
            </>
          )}
        </Part>

        {today?.written.trim() ? <Gathered text={today.written} /> : null}
      </div>

      <div className="shrink-0 pt-3">
        {refusal && <p role="alert" data-testid="ritual-error" className="mb-3 text-sm text-destructive">{refusal}</p>}
        <div className="flex items-center justify-between gap-4">
          <span>{ritual && <DeleteButton disabled={busy} onDelete={() => erase(ritual.id)} />}</span>
          <span className="flex items-center gap-2">
            {ritual && (
              <span title={saveFirst}>
                <Button type="button" variant="ghost" size="sm" data-testid="ritual-run" title={saveFirst}
                  disabled={dirty || busy} onClick={() => start(ritual.id, ritual.name)}>
                  {t("rituals.run_now")}
                </Button>
              </span>
            )}
            <Button type="button" size="sm" data-testid="ritual-save" disabled={!complete || busy} onClick={save}>
              {create.isPending || update.isPending ? t("rituals.saving") : t("rituals.save")}
            </Button>
          </span>
        </div>
      </div>
    </>
  );
}

/**
 * One ritual, written or changed in a dialog over the conversation: its name
 * and whether it is on, the phrases that start it, when they may start it,
 * what happens right away and what is gathered before. Everything the person
 * changes waits for Save. An existing ritual also says where it stands today
 * and can be started, gathered for or removed from here.
 */
export default function RitualDialog({ ritualId, onClose }: {
  /** The ritual to change; null writes a new one. */
  ritualId: string | null;
  onClose: () => void;
}) {
  const t = useT();
  const list = useRituals();
  const detail = useRitual(ritualId ?? "", { enabled: ritualId !== null });
  // Undefined while an existing ritual is still on its way.
  const ritual = ritualId === null ? null : detail.data?.ritual;

  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[80] bg-scrim/70 backdrop-blur-sm data-[state=open]:animate-in data-[state=open]:fade-in-0 motion-reduce:animate-none" />
        <Dialog.Content
          data-testid="ritual-dialog"
          aria-describedby={undefined}
          className={cn(
            "fixed left-1/2 top-1/2 z-[90] flex max-h-[min(84dvh,44rem)] w-[min(560px,calc(100vw-2rem))]",
            "-translate-x-1/2 -translate-y-1/2 flex-col overflow-y-auto rounded-lg bg-popover p-4 shadow-float outline-none",
            "data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 motion-reduce:animate-none",
          )}
        >
          <Dialog.Title className="sr-only">{ritual?.name || t("rituals.new")}</Dialog.Title>
          {ritual === undefined
            ? <p role="status" className="py-6 text-center text-sm text-muted-foreground">
              {detail.error ? detail.error.message : t("common.loading")}
            </p>
            : <RitualForm key={ritualId ?? "new"} ritual={ritual} today={detail.data?.today ?? null}
              limits={list.data?.limits} onClose={onClose} />}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
