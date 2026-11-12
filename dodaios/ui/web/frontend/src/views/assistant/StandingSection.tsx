/**
 * Standing tasks — what the assistant looks after over time on its own.
 *
 * One line says what this is; under it the tasks in the page's own grammar,
 * a hairline between them: what the assistant suggested first (Accept / Not
 * now), then what runs, then what is paused. A row says the goal, how far
 * the assistant may go, how often it looks, what the last look found and
 * when the next one comes; it opens the task's own page. "Add" unfolds a
 * small form in the label-column grammar. With nothing there yet the section
 * shows an example to start from, and says that asking in the chat works too.
 */
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { fill, useT, useUiLanguage } from "@/i18n";
import {
  sortStanding,
  useCreateStanding,
  useStandingAction,
  useStandingTasks,
  type StandingAutonomy,
  type StandingList,
  type StandingTask,
} from "@/lib/standingTasksApi";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { Section, SpecRow, TextAction } from "@/views/assistant/Section";
import { AutonomyChoice, Finding, PaceSelect, StateDot } from "@/views/assistant/standingParts";
import { lastFinding, lastLookLine, mannerLine, nextLookLine } from "@/views/assistant/standingWords";

/** What the form starts from: blank, or the example. */
interface Seed {
  title: string;
  goal: string;
}

const BLANK: Seed = { title: "", goal: "" };

function StandingForm({ seed, list, onClose }: { seed: Seed; list: StandingList; onClose: () => void }) {
  const t = useT();
  const pushToast = useEventStore((s) => s.pushToast);
  const create = useCreateStanding();
  const [title, setTitle] = useState(seed.title);
  const [goal, setGoal] = useState(seed.goal);
  const [how, setHow] = useState("");
  const [autonomy, setAutonomy] = useState<StandingAutonomy>("prepare");
  const [limits, setLimits] = useState("");
  const [interval, setIntervalMin] = useState(list.limits.default_interval_min);

  const acts = autonomy === "act";
  // Acting on its own needs the limits it acts inside, in the person's words.
  const needsLimits = acts && !limits.trim();
  const canSave = Boolean(title.trim() && goal.trim()) && !needsLimits && !create.isPending;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!canSave) return;
    create.mutate(
      {
        title: title.trim(),
        goal: goal.trim(),
        how: how.trim() || undefined,
        autonomy,
        limits: acts ? limits.trim() : undefined,
        interval_min: interval,
      },
      {
        onSuccess: () => {
          pushToast("success", t("standing.form_added"));
          onClose();
        },
      },
    );
  };

  return (
    <form data-testid="assistant-standing-form" onSubmit={submit} className="mt-2 border-b border-border pb-5">
      <div className="divide-y divide-border">
        <SpecRow label={<label htmlFor="standing-form-title" className="block pt-1">{t("standing.form_title_label")}</label>}>
          <Input
            id="standing-form-title"
            data-testid="assistant-standing-form-title"
            value={title}
            maxLength={120}
            autoFocus
            onChange={(e) => setTitle(e.target.value)}
            placeholder={t("standing.form_title_placeholder")}
          />
        </SpecRow>
        <SpecRow label={<label htmlFor="standing-form-goal" className="block pt-1">{t("standing.goal_label")}</label>}>
          <Textarea
            id="standing-form-goal"
            data-testid="assistant-standing-form-goal"
            value={goal}
            rows={3}
            onChange={(e) => setGoal(e.target.value)}
            placeholder={t("standing.form_goal_placeholder")}
          />
        </SpecRow>
        <SpecRow label={<label htmlFor="standing-form-how" className="block pt-1">{t("standing.how_label")}</label>}>
          <Textarea
            id="standing-form-how"
            data-testid="assistant-standing-form-how"
            value={how}
            rows={2}
            className="min-h-[60px]"
            onChange={(e) => setHow(e.target.value)}
            placeholder={t("standing.form_how_placeholder")}
          />
        </SpecRow>
        <SpecRow label={t("standing.autonomy_label")}>
          <AutonomyChoice
            testId="assistant-standing-form-level"
            value={autonomy}
            levels={list.autonomy}
            onChange={setAutonomy}
          />
        </SpecRow>
        {acts && (
          <SpecRow label={<label htmlFor="standing-form-limits" className="block pt-1">{t("standing.limits_label")}</label>}>
            <Textarea
              id="standing-form-limits"
              data-testid="assistant-standing-form-limits"
              value={limits}
              rows={2}
              className="min-h-[60px]"
              aria-describedby="standing-form-limits-hint"
              onChange={(e) => setLimits(e.target.value)}
              placeholder={t("standing.form_limits_placeholder")}
            />
            <p
              id="standing-form-limits-hint"
              data-testid="assistant-standing-form-limits-hint"
              className={cn("mt-2 text-sm", needsLimits ? "text-foreground" : "text-muted-foreground")}
            >
              {t("standing.act_needs_limits")}
            </p>
          </SpecRow>
        )}
        <SpecRow label={<label htmlFor="standing-form-pace" className="block pt-1">{t("standing.pace_label")}</label>}>
          <PaceSelect
            id="standing-form-pace"
            testId="assistant-standing-form-pace"
            value={interval}
            limits={list.limits}
            onChange={setIntervalMin}
          />
        </SpecRow>
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <p className="min-w-0 max-w-[34rem] text-sm text-muted-foreground">
          {create.error ? (
            <span role="alert" className="text-destructive">{create.error.message}</span>
          ) : (
            t("standing.form_note")
          )}
        </p>
        <div className="flex items-center gap-5">
          <TextAction onClick={onClose} data-testid="assistant-standing-form-cancel">{t("standing.cancel")}</TextAction>
          <Button type="submit" size="sm" disabled={!canSave} data-testid="assistant-standing-form-submit">
            {create.isPending ? t("standing.saving") : t("standing.form_submit")}
          </Button>
        </div>
      </div>
    </form>
  );
}

function TaskRow({
  task,
  busy,
  onOpen,
  onAccept,
  onDecline,
}: {
  task: StandingTask;
  busy: boolean;
  onOpen: () => void;
  onAccept: () => void;
  onDecline: () => void;
}) {
  const t = useT();
  const lang = useUiLanguage();
  const proposed = task.state === "proposed";
  const finding = lastFinding(task, t);
  const looked = lastLookLine(task, t, lang);
  const next = nextLookLine(task, t, lang);

  return (
    <li data-testid={`assistant-standing-${task.id}`} data-state={task.state} className="flex items-start gap-8 py-4">
      <button
        type="button"
        data-testid={`assistant-standing-open-${task.id}`}
        onClick={onOpen}
        className="group min-w-0 flex-1 rounded-sm text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="flex items-center gap-2.5 text-base leading-7">
          <StateDot state={task.state} />
          <span className="min-w-0 truncate font-medium text-foreground-strong underline-offset-4 group-hover:underline">
            {task.title}
          </span>
          {task.state !== "active" && (
            <span className="shrink-0 text-sm text-muted-foreground">{t(`standing.state_${task.state}`)}</span>
          )}
        </span>
        <span className="block pl-4">
          <span className="line-clamp-2 max-w-reading text-base leading-7 text-foreground">{task.goal}</span>
          <span className="mt-1 block text-sm text-muted-foreground">{mannerLine(task, t, lang)}</span>
          {proposed && task.reason && (
            <span className="mt-1 line-clamp-2 max-w-reading text-sm text-muted-foreground">
              {fill(t("standing.reason"), { reason: task.reason })}
            </span>
          )}
          {!proposed && (
            <span data-testid={`assistant-standing-last-${task.id}`} className="mt-1 line-clamp-2 max-w-reading text-sm text-muted-foreground">
              {looked ?? t("standing.never_looked")}
              {finding && (
                <>
                  {" · "}
                  <Finding task={task} />
                </>
              )}
            </span>
          )}
        </span>
      </button>
      <div className="flex shrink-0 flex-col items-end gap-2 pt-0.5 text-right">
        {proposed ? (
          <>
            <Button type="button" size="sm" disabled={busy} onClick={onAccept} data-testid={`assistant-standing-accept-${task.id}`}>
              {t("standing.accept")}
            </Button>
            <TextAction disabled={busy} onClick={onDecline} data-testid={`assistant-standing-decline-${task.id}`}>
              {t("standing.decline")}
            </TextAction>
          </>
        ) : (
          next && <span className="pt-1 text-sm tabular-nums text-muted-foreground">{next}</span>
        )}
      </div>
    </li>
  );
}

function ListSkeleton({ label }: { label: string }) {
  return (
    <div role="status" aria-busy="true" aria-label={label} className="mt-2 divide-y divide-border">
      {[0, 1].map((i) => (
        <div key={i} className="flex flex-col gap-3 py-4">
          <div className="h-4 w-56 max-w-full animate-pulse rounded-full bg-secondary" />
          <div className="h-4 w-2/3 animate-pulse rounded-full bg-secondary" />
          <div className="h-3.5 w-72 max-w-full animate-pulse rounded-full bg-secondary" />
        </div>
      ))}
    </div>
  );
}

export function StandingSection({
  onOpen,
  focus = false,
  onFocused,
}: {
  onOpen: (taskId: string) => void;
  /** Bring the section into view: the person came here for it. */
  focus?: boolean;
  onFocused?: () => void;
}) {
  const t = useT();
  const pushToast = useEventStore((s) => s.pushToast);
  const list = useStandingTasks();
  const action = useStandingAction();
  const [seed, setSeed] = useState<Seed | null>(null);
  const anchor = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!focus) return;
    anchor.current?.scrollIntoView?.({ block: "start" });
    onFocused?.();
  }, [focus, onFocused]);

  const data = list.data;
  const tasks = useMemo(() => sortStanding(data?.tasks ?? []), [data]);
  const available = data?.available === true;
  const adding = seed !== null && data !== undefined && available;
  const busyId = action.isPending ? action.variables?.id : undefined;

  const decide = (task: StandingTask, verb: "accept" | "decline") =>
    action.mutate({ id: task.id, action: verb }, { onError: (e) => pushToast("error", e.message) });

  return (
    <div ref={anchor} className="scroll-mt-6">
      <Section
        testId="assistant-standing"
        title={t("standing.title")}
        action={
          available && !adding ? (
            <TextAction onClick={() => setSeed(BLANK)} data-testid="assistant-standing-add">
              {t("standing.add")}
            </TextAction>
          ) : undefined
        }
      >
        <p className="max-w-reading text-base leading-7 text-muted-foreground">{t("standing.hint")}</p>

        {list.isLoading && <ListSkeleton label={t("common.loading")} />}

        {list.error && !data && (
          <div role="alert" data-testid="assistant-standing-error" className="mt-3">
            <p className="text-base text-foreground">{t("standing.error_title")}</p>
            <p className="mt-1 text-sm text-muted-foreground">{list.error.message}</p>
            <TextAction className="mt-2" onClick={() => void list.refetch()}>
              {t("standing.retry")}
            </TextAction>
          </div>
        )}

        {data && !available && (
          <p data-testid="assistant-standing-unavailable" className="mt-3 flex max-w-reading items-start gap-2.5 text-base leading-7 text-foreground">
            <span aria-hidden className="mt-[11px] h-1.5 w-1.5 shrink-0 rounded-full bg-warning" />
            {t("standing.unavailable")}
          </p>
        )}

        {adding && <StandingForm seed={seed} list={data} onClose={() => setSeed(null)} />}

        {data && available && tasks.length === 0 && !adding && (
          <div data-testid="assistant-standing-empty" className="mt-2">
            <p className="max-w-reading text-base leading-7 text-foreground">{t("standing.empty")}</p>
            <div className="mt-1 divide-y divide-border">
              <SpecRow label={t("standing.example_label")}>
                <p>
                  <span className="font-medium text-foreground-strong">{t("standing.example_title")}: </span>
                  {t("standing.example_goal")}
                </p>
                <TextAction
                  className="mt-1"
                  data-testid="assistant-standing-example"
                  onClick={() => setSeed({ title: t("standing.example_title"), goal: t("standing.example_goal") })}
                >
                  {t("standing.example_use")}
                </TextAction>
              </SpecRow>
              <SpecRow label={t("standing.chat_label")}>{t("standing.chat_hint")}</SpecRow>
            </div>
          </div>
        )}

        {tasks.length > 0 && (
          <ul data-testid="assistant-standing-list" className="mt-2 divide-y divide-border">
            {tasks.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                busy={busyId === task.id}
                onOpen={() => onOpen(task.id)}
                onAccept={() => decide(task, "accept")}
                onDecline={() => decide(task, "decline")}
              />
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
