/**
 * Teams in the office. The team room's board opens every team; a team
 * studio's board opens that studio's team. Either way this is the same sheet:
 * who is in the team and what they do right now, meet at the table, open the
 * team's real chat, rename it, change its members, delete it, and put a new
 * team together.
 *
 * Teams are the existing society chat groups; the office adds no backend
 * contract. A meeting is purely spatial — members walk to the team room and
 * sit down — and never interrupts an agent that is working.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { MessagesSquare, Pencil, Plus, Users } from "lucide-react";
import { useT } from "@/i18n";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  createSocietyChatGroup, deleteSocietyChatGroup, updateSocietyChatGroup, useSocietyChatGroups, type SocietyChatGroup,
} from "@/lib/societyChatGroups";
import { cn } from "@/lib/utils";
import type { SocietyAgent } from "../data";
import type { OfficeLayout, Point, Studio } from "./officeLayout";
import type { NavGrid } from "./officeNav";
import { stationOf } from "./stations";
import { useOfficeStore } from "./officeStore";
import { agentPositions } from "./walkerRegistry";
import { boardSeats, MEETING_MS, meetingProgress, meetingSeats, minutesLeft } from "./teamMeeting";
import type { OfficeActions } from "./OfficePanels";
import { AgentFace } from "./AgentFace";
import { useTeamwork } from "./teamwork";
import "./teamRoom.css";

const GROUPS_KEY = ["society", "chat-groups"] as const;
/** Above this many agents the picker gets a search field. */
const SEARCH_FROM = 7;
/** Faces shown in a team's row before the rest fold into "+n". */
const STACK_MAX = 6;

/** The studio whose board was used: its team (null = the studio of agents without a team) and who sits there. */
export interface TeamFocus {
  teamId: string | null; members: readonly string[];
  /** The studio itself: its team meets at its own board instead of the table. `grid` is the floor's nav grid when the host has it. */
  studio?: Studio; grid?: NavGrid;
}

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function StateDot({ state }: { state: SocietyAgent["state"] }) {
  return <i className="office-dot" data-state={state} aria-hidden />;
}

/** An agent's face in these lists: its symbol on the neutral tile (AgentFace.tsx). */
const Face = AgentFace;

/** A team's members as overlapping faces, each with its state dot. */
function MemberStack({ agents }: { agents: SocietyAgent[] }) {
  const t = useT();
  const shown = agents.slice(0, STACK_MAX);
  return (
    <span className="team-stack">
      {shown.map((agent) => (
        <span key={agent.agentId} className="team-face" title={`${agent.name} · ${t(`society.office.state_${agent.state}`)}`}>
          <Face agent={agent} />
          <StateDot state={agent.state} />
        </span>
      ))}
      {agents.length > shown.length && <span className="team-face team-face-more office-face" aria-hidden>+{agents.length - shown.length}</span>}
    </span>
  );
}

/** Where the person stands to join a meeting: just south of the chairs, facing the table. */
function tableApproach(layout: OfficeLayout): Point | null {
  const table = layout.furniture.find((f) => f.kind === "meetingTable");
  return table ? { x: table.x, z: table.z + 2.1 } : null;
}

/** Checkbox list of agents with an optional search field and quick picks. */
function MemberPicker({ agents, selected, onToggle, onSet }: {
  agents: SocietyAgent[]; selected: string[]; onToggle: (id: string) => void; onSet: (ids: string[]) => void;
}) {
  const t = useT();
  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();
  const shown = needle ? agents.filter((a) => `${a.name} ${a.title}`.toLowerCase().includes(needle)) : agents;
  const free = agents.filter((a) => a.state === "idle").map((a) => a.agentId);
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{t("society.office.team_members_label")}</span>
        <span className="text-xs text-muted-foreground" aria-live="polite">{t("society.office.team_selected").replace("{0}", String(selected.length))}</span>
        <span className="ml-auto flex gap-1">
          <Button type="button" variant="ghost" size="sm" disabled={free.length === 0} onClick={() => onSet([...new Set([...selected, ...free])])}>
            {t("society.office.team_pick_idle")}
          </Button>
          <Button type="button" variant="ghost" size="sm" disabled={selected.length === 0} onClick={() => onSet([])}>
            {t("society.office.team_pick_clear")}
          </Button>
        </span>
      </div>
      {agents.length >= SEARCH_FROM && (
        <Input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("society.office.team_search")}
          aria-label={t("society.office.team_search")} />
      )}
      {shown.length === 0 ? <p className="text-sm text-muted-foreground">{t("society.office.team_no_match")}</p> : (
        <div className="team-picker-list min-h-0 overflow-y-auto rounded-md border border-border p-1" role="group" aria-label={t("society.office.team_members_label")}>
          {shown.map((agent) => (
            <label key={agent.agentId} className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-1.5 hover:bg-secondary">
              <input type="checkbox" className="accent-primary" checked={selected.includes(agent.agentId)} onChange={() => onToggle(agent.agentId)} />
              <Face agent={agent} />
              <span className="min-w-0 flex-1 truncate text-sm">{agent.name}</span>
              {agent.title && <span className="max-w-[40%] truncate text-xs text-muted-foreground">{agent.title}</span>}
              <StateDot state={agent.state} />
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * The team the person called together right now: who stands or sits there,
 * who is coming, who keeps working. It is a gathering on the map and says so
 * — nothing is posted to the team and no round runs because of it, so it
 * carries no "live" mark (that belongs to a real round, see teamStatus.ts).
 * The sheet shows it as a banner; the HUD shows it as a small card while the
 * sheet is closed, and also lets the team go when its time is up.
 */
export function MeetingStatus({ agents, layout, actions, compact = false }: {
  agents: readonly SocietyAgent[]; layout: OfficeLayout; actions: OfficeActions; compact?: boolean;
}) {
  const t = useT();
  const meeting = useOfficeStore((s) => s.meeting);
  const summons = useOfficeStore((s) => s.summons);
  const endMeeting = useOfficeStore((s) => s.endMeeting);
  const requestWalk = useOfficeStore((s) => s.requestWalk);
  const [now, setNow] = useState(() => Date.now());
  // Positions live outside React; a one-second tick keeps the seat count honest.
  useEffect(() => {
    if (!meeting) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [meeting]);
  useEffect(() => { if (meeting && meeting.untilMs <= now) endMeeting(); }, [meeting, now, endMeeting]);
  if (!meeting || meeting.untilMs <= now) return null;
  const progress = meetingProgress(meeting, agents, summons, agentPositions);
  const present = meeting.members.length - progress.missing.length;
  const nameOf = (id: string) => agents.find((a) => a.agentId === id)?.name ?? id;
  // A meeting at a studio's board is joined in front of that board; any other at the team room's table.
  const atBoard = !!meeting.boardId;
  const approach = atBoard ? stationOf(layout, { kind: "team", id: meeting.boardId as string })?.approach ?? null : tableApproach(layout);
  return (
    <section className={cn("team-meeting", compact && "office-card")} data-compact={compact || undefined} data-office-ui aria-live="polite">
      <p className="team-meeting-title">{t(atBoard ? "society.office.gather_board" : "society.office.gather_table").replace("{0}", meeting.name)}</p>
      <p className="team-meeting-line">
        {t(atBoard ? "society.office.meeting_status_board" : "society.office.meeting_status")
          .replace("{0}", String(progress.seated.length)).replace("{1}", String(present))
          .replace("{2}", String(minutesLeft(meeting, now)))}
      </p>
      {progress.busy.length > 0 && (
        <p className="team-meeting-line">{t("society.office.meeting_busy").replace("{0}", progress.busy.map(nameOf).join(", "))}</p>
      )}
      {!compact && <p className="team-meeting-line">{t("society.office.gather_note")}</p>}
      <div className="flex flex-wrap gap-2 pt-1">
        {actions.onOpenGroup && (
          <Button type="button" size="sm" onClick={() => actions.onOpenGroup?.(meeting.groupId)}>{t("society.office.team_chat")}</Button>
        )}
        {approach && <Button type="button" size="sm" variant="outline" onClick={() => requestWalk(approach)}>{t(atBoard ? "society.office.meeting_join_board" : "society.office.meeting_join")}</Button>}
        <Button type="button" size="sm" variant="outline" onClick={endMeeting}>{t("society.office.gather_end")}</Button>
      </div>
    </section>
  );
}

/** One team: who is in it, meet / chat, and an editor that unfolds in place. `detail` also lists every member. */
function TeamCard({ group, agents, layout, sample, actions, detail = false, onMeet, board = null }: {
  group: SocietyChatGroup; agents: SocietyAgent[]; layout: OfficeLayout; sample: boolean; actions: OfficeActions;
  detail?: boolean; onMeet?: () => void;
  /** This team's own studio, when the sheet was opened from its board: the team meets there. */
  board?: { studio: Studio; grid?: NavGrid } | null;
}) {
  const t = useT();
  const client = useQueryClient();
  const meeting = useOfficeStore((s) => s.meeting);
  const startMeeting = useOfficeStore((s) => s.startMeeting);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(group.name);
  const [members, setMembers] = useState<string[]>(group.members);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const present = group.members.map((id) => agents.find((a) => a.agentId === id)).filter((a): a is SocietyAgent => !!a);
  const working = present.filter((a) => a.state === "working").length;
  const lead = present.find((a) => a.agentId === group.lead_agent_id);
  const inMeeting = !!meeting && meeting.groupId === group.group_id && meeting.untilMs > Date.now();
  // A round of this team is answering right now (the backend's word): the only thing that is called live.
  const live = useTeamwork((s) => !!s.rounds[group.group_id]?.running);

  const meet = () => {
    const ids = present.map((a) => a.agentId);
    const meeting = { groupId: group.group_id, name: group.name, members: ids, untilMs: Date.now() + MEETING_MS };
    // From its own studio board the team gathers right there; from the team room it sits down at the table.
    if (board?.studio.board) startMeeting({ ...meeting, boardId: board.studio.board.id }, boardSeats(layout, board.studio, ids, board.grid));
    else startMeeting(meeting, meetingSeats(layout, ids));
    onMeet?.();
  };
  const editor = useRef<HTMLDivElement>(null);
  const openEditor = () => { setName(group.name); setMembers(group.members); setConfirmDelete(false); setError(""); setEditing(true); };
  // A team far down the list: its editor, with the Save button, comes into view.
  useEffect(() => { if (editing) editor.current?.scrollIntoView?.({ block: "nearest" }); }, [editing]);
  const save = async () => {
    if (members.length < 2 || busy) return;
    setBusy(true); setError("");
    try {
      await updateSocietyChatGroup(group.group_id, name.trim() || group.name, members);
      await client.invalidateQueries({ queryKey: GROUPS_KEY });
      setEditing(false);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (busy) return;
    setBusy(true); setError("");
    try {
      await deleteSocietyChatGroup(group.group_id);
      if (inMeeting) useOfficeStore.getState().endMeeting();
      await client.invalidateQueries({ queryKey: GROUPS_KEY });
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  };

  return (
    <li className="team-card rounded-xl border border-border bg-background" data-live={live || undefined} data-called={inMeeting || undefined}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 p-4">
        <MemberStack agents={present} />
        <div className="grid min-w-0 flex-1 gap-0.5">
          <span className="flex min-w-0 items-center gap-2">
            <span className="truncate text-sm font-semibold" title={group.name}>{group.name}</span>
            {live && <span className="team-live-mark"><i aria-hidden />{t("society.office.team_live")}</span>}
          </span>
          <span className="text-xs text-muted-foreground">
            {t("society.office.team_members").replace("{0}", String(present.length))}
            {working > 0 ? ` · ${t("society.office.team_working").replace("{0}", String(working))}` : ""}
            {lead ? ` · ${t("society.office.team_lead").replace("{0}", lead.name)}` : ""}
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" disabled={inMeeting || present.length === 0}
            aria-label={t(board ? "society.office.team_gather_board_label" : "society.office.team_gather_label").replace("{0}", group.name)} onClick={meet}>
            <Users aria-hidden />{inMeeting ? t("society.office.team_called") : t(board ? "society.office.team_meet_board" : "society.office.team_meet")}
          </Button>
          {actions.onOpenGroup && (
            <Button type="button" size="sm" variant="outline" aria-label={t("society.office.team_open_label").replace("{0}", group.name)}
              onClick={() => actions.onOpenGroup?.(group.group_id)}><MessagesSquare aria-hidden />{t("society.office.team_chat")}</Button>
          )}
          {!sample && !editing && (
            <Button type="button" size="sm" variant="ghost" onClick={openEditor}><Pencil aria-hidden />{t("society.office.team_edit")}</Button>
          )}
        </div>
      </div>
      {detail && !editing && present.length > 0 && (
        <ul className="grid gap-0.5 border-t border-border p-2">
          {present.map((agent) => (
            <li key={agent.agentId} className="flex items-center gap-3 rounded-md px-2 py-1.5">
              <Face agent={agent} />
              <span className="min-w-0 flex-1 truncate text-sm">{agent.name}</span>
              <span className="flex items-center gap-1.5 text-xs text-muted-foreground"><StateDot state={agent.state} />{t(`society.office.state_${agent.state}`)}</span>
              <Button type="button" size="sm" variant="ghost" aria-label={t("society.office.prompt_agent").replace("{0}", agent.name)}
                onClick={() => useOfficeStore.getState().select({ kind: "agent", id: agent.agentId })}>{t("society.office.action_talk")}</Button>
            </li>
          ))}
        </ul>
      )}
      {editing && (
        <div ref={editor} className="grid gap-3 border-t border-border p-4">
          <label className="grid gap-1 text-sm font-medium">
            {t("society.office.team_name")}
            <Input value={name} maxLength={60} onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void save(); } }} />
          </label>
          <MemberPicker agents={agents} selected={members}
            onToggle={(id) => setMembers((m) => (m.includes(id) ? m.filter((x) => x !== id) : [...m, id]))} onSet={setMembers} />
          {members.length < 2 && <p className="text-xs text-muted-foreground">{t("society.office.team_edit_need_more")}</p>}
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" size="sm" disabled={busy || members.length < 2} aria-busy={busy} onClick={() => void save()}>{t("society.office.team_save")}</Button>
            <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setEditing(false)}>{t("society.office.team_cancel")}</Button>
            <span className="ml-auto">
              {confirmDelete ? (
                <Button type="button" size="sm" variant="destructive" disabled={busy} onClick={() => void remove()}>{t("society.office.team_delete_confirm")}</Button>
              ) : (
                <button type="button" className="text-xs text-destructive underline underline-offset-2 disabled:opacity-50" disabled={busy}
                  onClick={() => setConfirmDelete(true)}>{t("society.office.team_delete")}</button>
              )}
            </span>
          </div>
        </div>
      )}
      {error && <p role="alert" className="px-4 pb-3 text-xs text-destructive">{error}</p>}
    </li>
  );
}

export function TeamRoomPanel({ agents, layout, sample, actions, focus = null, onMeet, compose = false }: {
  agents: SocietyAgent[]; layout: OfficeLayout; sample: boolean; actions: OfficeActions;
  /** Opened from a team studio's board: show that studio's team first. */
  focus?: TeamFocus | null;
  /** A team was sent to the table (the sheet steps aside so the person sees them gather). */
  onMeet?: () => void;
  /** Open on the new-team form (the free plot's stand: "start a team here"). */
  compose?: boolean;
}) {
  const t = useT();
  const client = useQueryClient();
  const teamDraft = useOfficeStore((s) => s.teamDraft);
  const toggleDraft = useOfficeStore((s) => s.toggleDraft);
  const clearDraft = useOfficeStore((s) => s.clearDraft);
  const groups = useSocietyChatGroups(!sample);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [created, setCreated] = useState("");
  const [everyTeam, setEveryTeam] = useState(false);
  const teams = useMemo(() => [...(groups.data ?? [])].sort((a, b) => b.updated_ms - a.updated_ms), [groups.data]);
  const members = teamDraft.filter((id) => agents.some((a) => a.agentId === id));
  // The new-team form stays folded behind a button once teams exist, unless agents were already picked on the map.
  const [composing, setComposing] = useState(compose);
  const studioTeam = focus?.teamId ? teams.find((g) => g.group_id === focus.teamId) ?? null : null;
  const studioOnly = !!focus && !everyTeam;
  const showComposer = composing || members.length > 0 || (!studioOnly && teams.length === 0 && !groups.isLoading && !groups.isError);
  const canCreate = !sample && !busy && members.length >= 2;

  const setDraft = (ids: string[]) => {
    clearDraft();
    ids.forEach((id) => toggleDraft(id));
  };
  const create = async () => {
    if (!canCreate) return;
    setBusy(true); setError(""); setCreated("");
    try {
      const names = members.map((id) => agents.find((a) => a.agentId === id)?.name ?? id);
      const group = await createSocietyChatGroup(name.trim() || names.join(" + "), members);
      await client.invalidateQueries({ queryKey: GROUPS_KEY });
      useOfficeStore.getState().startMeeting(
        { groupId: group.group_id, name: group.name, members, untilMs: Date.now() + MEETING_MS }, meetingSeats(layout, members));
      clearDraft();
      setName("");
      setComposing(false);
      setCreated(group.name);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const poolMembers = focus && !focus.teamId ? agents.filter((a) => focus.members.includes(a.agentId)) : [];
  const shownTeams = studioOnly ? (studioTeam ? [studioTeam] : []) : teams;

  return (
    <>
      <MeetingStatus agents={agents} layout={layout} actions={actions} />
      {sample && <p className="text-sm text-muted-foreground">{t("society.office.sample")}</p>}
      {created && <p className="text-sm" role="status">{t("society.office.team_created").replace("{0}", created)}</p>}

      <section className="grid gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">{t(showComposer ? "society.office.team_new" : studioOnly ? "society.office.team_this" : "society.office.team_yours")}</h3>
          {!showComposer && !sample && (
            <Button type="button" size="sm" variant="outline" onClick={() => {
              // From the studio of agents without a team, the people sitting there are the obvious first pick.
              if (studioOnly && poolMembers.length > 0 && members.length === 0) setDraft(poolMembers.map((a) => a.agentId));
              setComposing(true);
            }}><Plus aria-hidden />{t("society.office.team_new")}</Button>
          )}
        </div>
        {groups.isError && <p role="alert" className="text-sm text-destructive">{t("society.office.team_load_error").replace("{0}", errorText(groups.error))}</p>}

        {showComposer && (
          <section className="grid gap-3" aria-label={t("society.office.team_new")}>
            <p className="text-sm text-muted-foreground">{t("society.office.team_body")}</p>
            {agents.length === 0 ? <p className="text-sm text-muted-foreground">{t("society.office.manage_empty")}</p> : (
              <>
                <label className="grid gap-1 text-sm font-medium">
                  {t("society.office.team_name")}
                  <Input value={name} maxLength={60} onChange={(e) => setName(e.target.value)} placeholder={t("society.office.team_name_placeholder")}
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void create(); } }} />
                </label>
                <MemberPicker agents={agents} selected={members} onToggle={toggleDraft} onSet={setDraft} />
              </>
            )}
            {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
            {/* Pinned to the sheet's lower edge, so the button is in reach however long the list above it is. */}
            <div className="team-footer">
              <Button type="button" size="sm" disabled={!canCreate} aria-busy={busy} onClick={() => void create()}>
                {t("society.office.team_create").replace("{0}", String(members.length))}
              </Button>
              {(teams.length > 0 || studioOnly) && (
                <Button type="button" size="sm" variant="outline" onClick={() => { setComposing(false); clearDraft(); }}>{t("society.office.team_cancel")}</Button>
              )}
              {!sample && members.length < 2 && agents.length >= 2 && <span className="text-xs text-muted-foreground">{t("society.office.team_need_more")}</span>}
            </div>
          </section>
        )}

        {!showComposer && shownTeams.length > 0 && (
          <ul className="grid list-none gap-3 p-0">
            {shownTeams.map((group) => (
              <TeamCard key={group.group_id} group={group} agents={agents} layout={layout} sample={sample} actions={actions}
                detail={studioOnly} onMeet={onMeet}
                board={focus?.studio?.board && group.group_id === focus.teamId ? { studio: focus.studio, grid: focus.grid } : null} />
            ))}
          </ul>
        )}
        {!showComposer && studioOnly && !studioTeam && !groups.isLoading && (
          <div className="grid gap-2 rounded-lg border border-dashed border-border p-4">
            <p className="text-sm text-muted-foreground">{t(focus?.teamId ? "society.office.team_gone" : "society.office.team_pool_body")}</p>
            {poolMembers.length > 0 && <MemberStack agents={poolMembers} />}
          </div>
        )}
        {!showComposer && studioOnly && teams.length > (studioTeam ? 1 : 0) && (
          <div><Button type="button" size="sm" variant="ghost" onClick={() => setEveryTeam(true)}>{t("society.office.team_all").replace("{0}", String(teams.length))}</Button></div>
        )}
      </section>
    </>
  );
}
