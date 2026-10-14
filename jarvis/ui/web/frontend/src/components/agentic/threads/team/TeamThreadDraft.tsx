import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Loader2, Plus, Send, X } from "lucide-react";
import { AgentMark } from "@/components/agentic/AgentMark";
import { BrandedSelect } from "@/components/ui/select";
import { fill, useT } from "@/i18n";
import type { IdeProject } from "@/lib/agenticIdeApi";
import {
  TEAM_THREAD_MODES,
  TEAM_THREAD_ROLES,
  TEAM_THREADS_KEY,
  startTeamThread,
  teamThreadKey,
  useTeamSeats,
  type TeamRole,
  type TeamSeatPick,
  type TeamThreadMode,
} from "@/lib/teamThreadsApi";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { useIdeThreadsStore } from "@/store/ideThreads";

/** Member 1 plans, member 2 builds, every further member reviews. */
const roleAt = (index: number): TeamRole => (index === 0 ? "planner" : index === 1 ? "builder" : "reviewer");

/** Exactly one planner and one builder, so every plan and every step is checked by someone else. */
const rolesValid = (team: TeamSeatPick[]) =>
  team.filter((pick) => pick.role === "planner").length === 1 && team.filter((pick) => pick.role === "builder").length === 1;

/**
 * A team thread before it starts: how the team works, who sits in it, and the task.
 *
 * The team opens on the seats that are ready, one per model family where
 * there are several; the person can swap, add and remove members. As peers
 * everyone plans and reviews; as planner and builder each member gets a role.
 * One prompt starts everything that follows.
 */
export function TeamThreadDraft({ project }: { project: IdeProject }) {
  const t = useT();
  const client = useQueryClient();
  const pushToast = useEventStore((state) => state.pushToast);
  const focusNonce = useIdeThreadsStore((state) => state.focusNonce);
  const seats = useTeamSeats();
  const [picks, setPicks] = useState<TeamSeatPick[] | null>(null);
  const [task, setTask] = useState("");
  const [mode, setMode] = useState<TeamThreadMode>("peers");
  const [starting, setStarting] = useState(false);

  // The suggested team, until the person changes it.
  useEffect(() => {
    if (picks === null && seats.data) setPicks(seats.data.default.map((pick) => ({ ...pick })));
  }, [picks, seats.data]);

  const ready = useMemo(() => (seats.data?.seats ?? []).filter((seat) => seat.ready), [seats.data]);
  const byId = useMemo(() => new Map((seats.data?.seats ?? []).map((seat) => [seat.provider, seat])), [seats.data]);
  const team = picks ?? [];
  const min = seats.data?.min_members ?? 2;
  const max = seats.data?.max_members ?? 4;
  const families = new Set(team.map((pick) => byId.get(pick.provider)?.family ?? pick.provider));
  const planned = mode === "planner_builder";
  // Roles follow the position until the person picks one.
  const cast = team.map((pick, index) => ({ ...pick, role: pick.role ?? roleAt(index) }));
  const rolesOk = !planned || rolesValid(cast);
  const canStart = !starting && task.trim().length > 0 && team.length >= min && team.length <= max && rolesOk;

  const setPick = (index: number, provider: string) => setPicks(team.map((pick, at) => at === index
    ? { provider, model: byId.get(provider)?.model ?? "", ...(pick.role ? { role: pick.role } : {}) } : pick));
  const setRole = (index: number, role: TeamRole) => setPicks(cast.map((pick, at) => (at === index ? { ...pick, role } : pick)));
  const add = () => {
    const unused = ready.find((seat) => !team.some((pick) => pick.provider === seat.provider)) ?? ready[0];
    if (unused) setPicks([...team, { provider: unused.provider, model: unused.model }]);
  };
  const remove = (index: number) => setPicks(team.filter((_, at) => at !== index));

  const start = async () => {
    if (!canStart) return;
    setStarting(true);
    try {
      const thread = await startTeamThread(planned
        ? { task: task.trim(), cwd: project.path, seats: cast, mode }
        : { task: task.trim(), cwd: project.path, seats: team.map(({ role: _role, ...pick }) => pick) });
      client.setQueryData(teamThreadKey(thread.team_id), thread);
      void client.invalidateQueries({ queryKey: TEAM_THREADS_KEY });
      // Filed under the project it was started in, wherever its folder lies.
      useIdeThreadsStore.getState().rememberProject(thread.team_id, project.id);
      useIdeThreadsStore.getState().openTeam(thread.team_id, project.id);
    } catch (error) {
      pushToast("error", error instanceof Error ? error.message : String(error));
      setStarting(false);
    }
  };

  const [before, after = ""] = t("team_threads.draft.title").split("{project}");
  return <div className="flex h-full min-h-0 flex-col items-center justify-center overflow-y-auto px-5 pb-10" data-testid="team-thread-draft">
    <div className="flex w-full max-w-3xl flex-col gap-5">
      {/* The form is a step away from what was open, never a place without a way back. */}
      <button type="button" onClick={() => useIdeThreadsStore.getState().cancelTeamDraft()} data-testid="team-draft-cancel"
        className="-mb-2 flex items-center gap-1.5 self-start rounded-md px-2 py-1 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <ArrowLeft aria-hidden className="h-3.5 w-3.5" />{t("team_threads.draft.cancel")}
      </button>
      <div className="text-center">
        <h2 className="text-2xl font-normal tracking-tight text-foreground sm:text-3xl">
          {before}<span className="font-semibold text-foreground-strong">{project.name}</span>{after}
        </h2>
        <p className="mx-auto mt-2 max-w-[62ch] text-sm text-muted-foreground">{t(planned ? "team_threads.draft.body_planned" : "team_threads.draft.body")}</p>
      </div>

      <div role="radiogroup" aria-label={t("team_threads.draft.mode")} data-testid="team-draft-mode"
        className="mx-auto flex rounded-full border border-border bg-secondary/40 p-0.5">
        {TEAM_THREAD_MODES.map((option) => <button key={option} type="button" role="radio" aria-checked={mode === option}
          data-testid={`team-draft-mode-${option}`} onClick={() => setMode(option)}
          className={cn(
            "rounded-full px-3.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            mode === option ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}>
          {t(`team_threads.mode.${option}`)}
        </button>)}
      </div>

      <section aria-label={t("team_threads.members")} className="flex flex-col gap-2">
        {seats.isLoading && <Loader2 role="status" aria-label={t("team_threads.loading")} className="mx-auto h-4 w-4 animate-spin text-muted-foreground" />}
        {seats.data && ready.length === 0 && <p role="alert" className="text-center text-sm text-warning">{t("team_threads.draft.none_ready")}</p>}
        {ready.length > 0 && <ul className="flex flex-wrap items-center justify-center gap-2">
          {cast.map((pick, index) => {
            const seat = byId.get(pick.provider);
            return <li key={index} className="flex items-center gap-1 rounded-full border border-border bg-secondary/40 py-1 pl-2 pr-1"
              data-testid={`team-draft-member-${index}`}>
              {seat?.agent ? <AgentMark agent={seat.agent} label={seat.label} variant="plain" size="sm" /> : null}
              <BrandedSelect ariaLabel={fill(t("team_threads.draft.member_n"), { number: index + 1 })}
                testId={`team-draft-select-${index}`} value={pick.provider} onValueChange={(value) => setPick(index, value)}
                className="min-w-[11rem]"
                options={ready.map((option) => ({ value: option.provider, label: option.label }))} />
              {planned && <BrandedSelect ariaLabel={fill(t("team_threads.draft.role_of"), { number: index + 1 })}
                testId={`team-draft-role-${index}`} value={pick.role} onValueChange={(value) => setRole(index, value as TeamRole)}
                className="min-w-[7.5rem]"
                options={TEAM_THREAD_ROLES.map((role) => ({ value: role, label: t(`team_threads.member_role.${role}`) }))} />}
              <button type="button" disabled={team.length <= min} onClick={() => remove(index)}
                aria-label={fill(t("team_threads.draft.remove_named"), { target: seat?.label ?? pick.provider })}
                className="rounded-full p-1 text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-30">
                <X className="h-3.5 w-3.5" />
              </button>
            </li>;
          })}
          {team.length < max && <li>
            <button type="button" onClick={add} data-testid="team-draft-add"
              className="flex items-center gap-1 rounded-full border border-dashed border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <Plus aria-hidden className="h-3.5 w-3.5" />{t("team_threads.draft.add")}
            </button>
          </li>}
        </ul>}
        {team.length >= min && families.size === 1 && <p className="text-center text-xs text-muted-foreground" data-testid="team-draft-same-family">
          {t("team_threads.notice.same_family")}
        </p>}
        {!rolesOk && <p role="alert" className="text-center text-xs text-warning" data-testid="team-draft-roles-invalid">
          {t("team_threads.draft.roles_invalid")}
        </p>}
      </section>

      <form onSubmit={(event) => { event.preventDefault(); void start(); }}
        className="flex items-end gap-1 rounded-[24px] border border-border bg-secondary px-2 py-1.5 focus-within:border-border-strong">
        <textarea key={focusNonce} autoFocus value={task} rows={3} onChange={(event) => setTask(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void start();
            }
          }}
          aria-label={t("team_threads.draft.placeholder")} placeholder={t("team_threads.draft.placeholder")}
          data-testid="team-draft-task"
          className="max-h-[260px] min-h-16 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-foreground outline-none placeholder:text-muted-foreground" />
        <button type="submit" disabled={!canStart} aria-label={t("team_threads.draft.start")} title={t("team_threads.draft.start")}
          data-testid="team-draft-start"
          className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-primary-foreground disabled:opacity-40">
          {starting ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Send className="h-3.5 w-3.5" aria-hidden />}
        </button>
      </form>
      <p className="text-center text-xs text-muted-foreground">{t(planned ? "team_threads.draft.bounds_planned" : "team_threads.draft.bounds")}</p>
    </div>
  </div>;
}
