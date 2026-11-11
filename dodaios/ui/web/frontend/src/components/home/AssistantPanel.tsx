import { lazy, Suspense, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Clock, FileText, Sparkles } from "lucide-react";
import { EarlierChatsLink } from "@/components/home/EarlierChatsLink";
import { chatRowLabel, useChatRows } from "@/components/home/chatRows";
import { MascotGigi } from "@/components/MascotGigi";
import { useRunLocale } from "@/components/runs/format";
import { humanSchedule } from "@/components/society/card/routines/humanSchedule";
import { Switch } from "@/components/ui/switch";
import { useSetSkillEnabled, useSkillsList } from "@/hooks/useSkills";
import { useVoiceEngineDisplay } from "@/hooks/useVoiceEngineDisplay";
import { useLocaleChunk, useT } from "@/i18n";
import { fetchLeadSession } from "@/lib/agentChatApi";
import { setTaskEnabled } from "@/lib/tasksApi";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { useSettingsJump } from "@/store/settingsJump";
import { useSoulProfile, type SoulFileId } from "@/views/assistant/api";

// A routine's or a file's own page is only fetched when one is opened.
const AssistantRoutineDialog = lazy(() => import("@/components/home/AssistantRoutineDialog"));
const AssistantFileDialog = lazy(() => import("@/components/home/AssistantFileDialog"));

/** The assistant's own id in the roster; its routines are the automations listed here. */
const ASSISTANT_ID = "jarvis";
const RECENTS_SHOWN = 4;
const SKILLS_SHOWN = 8;
const TAB_KEY = "jarvis.sidebar.assistantTab.v1";
const AGENT_TITLE_PREFIX = /^\[agent:[^\]]+\]\s*/i;
const AUTOMATIONS_KEY = ["sidebar", "automations"] as const;
const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

type Tab = "activity" | "library";

interface Automation {
  id: string;
  title: string;
  state: string;
  trigger: unknown;
}

function readTab(): Tab {
  try {
    return localStorage.getItem(TAB_KEY) === "library" ? "library" : "activity";
  } catch {
    return "activity";
  }
}

function useAutomations() {
  return useQuery({
    queryKey: AUTOMATIONS_KEY,
    staleTime: 30_000,
    refetchInterval: import.meta.env.MODE === "test" ? false : 60_000,
    retry: false,
    queryFn: async (): Promise<Automation[]> => {
      const response = await fetch(`/api/society/agents/${ASSISTANT_ID}/routines`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body = (await response.json()) as { routines?: { id?: string; title?: string; state?: string; trigger?: unknown }[] };
      return (body.routines ?? []).flatMap((row) =>
        row.id
          ? [{ id: row.id, title: (row.title ?? "").replace(AGENT_TITLE_PREFIX, "").trim(), state: row.state ?? "", trigger: row.trigger ?? null }]
          : [],
      );
    },
  });
}

/** The id of the one endless conversation, so the list of earlier chats can leave it out. */
function useConversationId(): string | null {
  const lead = useQuery({
    queryKey: ["sidebar", "conversation-id"],
    staleTime: 5 * 60_000,
    retry: false,
    queryFn: async () => (await fetchLeadSession()).session_id ?? null,
  });
  return lead.data ?? null;
}

/** A titled group: a quiet label and one card holding its rows. */
function Group({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-label={title} data-testid={`assistant-panel-${id}`} className="mt-4 first:mt-1">
      <h2 className="px-1 pb-1.5 text-sm text-muted-foreground">{title}</h2>
      <div className="overflow-hidden rounded-lg border border-border bg-card">{children}</div>
    </section>
  );
}

const ROW = "flex min-h-10 w-full min-w-0 items-center gap-2.5 px-3 py-1.5 text-left";
const ROW_BUTTON = cn(ROW, "transition-colors hover:bg-secondary", FOCUS);

/**
 * The assistant's panel, to the right of its conversation: who it is and what
 * belongs to it.
 *
 * Its face is the product's own mascot; face and name lead back to the
 * conversation. "Activity" holds what it
 * does on its own (its routines, each with a switch), how it is spoken to,
 * and the chats from before. "Library" holds what it keeps: its own files
 * (character, standing instructions, memory, what it knows about the person)
 * and its skills. Nothing of the Agentic IDE is listed here.
 */
export default function AssistantPanel({ onConversation }: { onConversation: () => void }) {
  const t = useT();
  useLocaleChunk("society");
  const locale = useRunLocale();
  const client = useQueryClient();
  const setActive = useEventStore((s) => s.setActiveSection);
  const automations = useAutomations();
  const profile = useSoulProfile();
  const skills = useSkillsList();
  const setSkillEnabled = useSetSkillEnabled();
  const voice = useVoiceEngineDisplay();
  const { rows, isActive, open: openRow } = useChatRows();
  const conversationId = useConversationId();
  const [tab, setTab] = useState<Tab>(readTab);
  const [routineId, setRoutineId] = useState<string | null>(null);
  const [fileId, setFileId] = useState<SoulFileId | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  const pickTab = (next: Tab) => {
    setTab(next);
    try { localStorage.setItem(TAB_KEY, next); } catch { /* a convenience only */ }
  };

  const toggleRoutine = async (routine: Automation, enabled: boolean) => {
    setPending(routine.id);
    try {
      await setTaskEnabled(routine.id, enabled);
    } catch (error) {
      useEventStore.getState().pushToast("error", error instanceof Error ? error.message : String(error));
    } finally {
      await client.invalidateQueries({ queryKey: AUTOMATIONS_KEY });
      setPending(null);
    }
  };

  const openSettings = (group: string) => {
    useSettingsJump.getState().request(group);
    setActive("settings");
  };

  const routines = automations.data ?? [];
  // The conversation itself is the face above, not one of the chats from before.
  const recents = rows.filter((row) => row.id !== conversationId).slice(0, RECENTS_SHOWN);
  const files = profile.data?.files ?? [];
  const skillRows = [...(skills.data?.skills ?? [])]
    .filter((skill) => skill.state === "active" || skill.state === "disabled")
    .sort((a, b) => Number(b.state === "active") - Number(a.state === "active") || a.name.localeCompare(b.name));
  const name = t("sidebar.conversation");

  return (
    <aside aria-label={name} data-testid="assistant-panel"
      className="flex h-full w-[320px] shrink-0 flex-col overflow-y-auto border-l border-border px-3 pb-4 pt-8 scrollbar-jarvis">
      <button type="button" data-testid="assistant-panel-conversation" onClick={onConversation} title={name}
        className={cn("mx-auto mt-3 flex flex-col items-center gap-2 rounded-lg px-4 py-2", FOCUS)}>
        <MascotGigi size={72} enableComments={false} />
        <span className="text-lg font-semibold text-foreground-strong">{name}</span>
      </button>

      <div role="tablist" aria-label={name} className="mx-auto mt-1 flex items-center gap-1">
        {(["activity", "library"] as const).map((id) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} data-testid={`assistant-panel-tab-${id}`}
            onClick={() => pickTab(id)}
            className={cn("rounded-md px-2.5 py-1 text-sm transition-colors", FOCUS,
              tab === id ? "bg-secondary text-foreground-strong" : "text-muted-foreground hover:text-foreground")}>
            {t(`sidebar.tab_${id}`)}
          </button>
        ))}
      </div>

      {tab === "activity" ? (
        <div role="tabpanel" className="mt-3">
          <Group id="automations" title={t("sidebar.automations")}>
            {routines.map((routine) => {
              const active = routine.state !== "paused";
              const sentence = humanSchedule(routine.trigger, { t, locale });
              return (
                <div key={routine.id} className={cn(ROW, "border-b border-border last:border-b-0")}>
                  <button type="button" data-testid={`assistant-automation-${routine.id}`} onClick={() => setRoutineId(routine.id)} title={routine.title}
                    className={cn("flex min-w-0 flex-1 items-center gap-2.5 rounded-md text-left", FOCUS)}>
                    <Clock aria-hidden strokeWidth={1.75} className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1">
                      <span className={cn("block truncate text-sm", active ? "text-foreground" : "text-muted-foreground")}>{routine.title}</span>
                      {sentence && <span className="block truncate text-sm text-muted-foreground">{sentence}</span>}
                    </span>
                  </button>
                  <Switch aria-label={routine.title} data-testid={`assistant-automation-switch-${routine.id}`}
                    checked={active} disabled={pending === routine.id}
                    onCheckedChange={(enabled) => void toggleRoutine(routine, enabled)} />
                </div>
              );
            })}
            {routines.length === 0 && (
              <p data-testid="assistant-automations-empty" className={cn(ROW, "text-sm text-muted-foreground")}>
                {automations.isLoading ? t("common.loading") : t("sidebar.automations_empty")}
              </p>
            )}
          </Group>

          <Group id="voice" title={t("sidebar.voice")}>
            <button type="button" data-testid="assistant-voice-model" onClick={() => openSettings("voice")}
              className={cn(ROW_BUTTON, "border-b border-border")}>
              <span className="min-w-0 flex-1 truncate text-sm text-foreground">{t("sidebar.voice_model")}</span>
              <span className="min-w-0 truncate text-sm text-muted-foreground">{voice.providerLabel}</span>
              <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            </button>
            <button type="button" data-testid="assistant-voice-wake" onClick={() => openSettings("wake-word")} className={ROW_BUTTON}>
              <span className="min-w-0 flex-1 truncate text-sm text-foreground">{t("sidebar.wake_word")}</span>
              <span className="min-w-0 truncate text-sm text-muted-foreground">{profile.data?.wake_phrase ?? ""}</span>
              <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            </button>
          </Group>

          <Group id="recents" title={t("sidebar.recent_chats")}>
            {recents.map((row) => {
              const label = chatRowLabel(row, t);
              const onStage = isActive(row);
              return (
                <button key={`${row.kind}:${row.id}`} type="button" data-testid={`assistant-recent-${row.id}`}
                  onClick={() => openRow(row)} title={label.text} aria-current={onStage ? "page" : undefined}
                  className={cn(ROW_BUTTON, "border-b border-border", onStage && "bg-secondary")}>
                  <span className={cn("min-w-0 flex-1 truncate text-sm", label.untitled ? "text-muted-foreground" : "text-foreground")}>{label.text}</span>
                </button>
              );
            })}
            <EarlierChatsLink />
          </Group>
        </div>
      ) : (
        <div role="tabpanel" className="mt-3">
          <Group id="files" title={t("assistant_view.files_title")}>
            {files.map((file) => (
              <button key={file.id} type="button" data-testid={`assistant-file-${file.id}`} onClick={() => setFileId(file.id)}
                className={cn(ROW_BUTTON, "border-b border-border last:border-b-0")}>
                <FileText aria-hidden strokeWidth={1.75} className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate text-sm text-foreground">{file.filename}</span>
                <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              </button>
            ))}
            {files.length === 0 && (
              <p className={cn(ROW, "text-sm text-muted-foreground")}>{profile.isLoading ? t("common.loading") : t("sidebar.files_empty")}</p>
            )}
          </Group>

          <Group id="skills" title={t("nav.skills")}>
            {skillRows.slice(0, SKILLS_SHOWN).map((skill) => (
              <div key={skill.name} className={cn(ROW, "border-b border-border")}>
                <Sparkles aria-hidden strokeWidth={1.75} className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span title={skill.name} className={cn("min-w-0 flex-1 truncate text-sm", skill.state === "active" ? "text-foreground" : "text-muted-foreground")}>{skill.name}</span>
                <Switch aria-label={skill.name} data-testid={`assistant-skill-switch-${skill.name}`}
                  checked={skill.state === "active"} disabled={setSkillEnabled.isPending}
                  onCheckedChange={(enabled) => setSkillEnabled.mutate({ name: skill.name, enabled })} />
              </div>
            ))}
            <button type="button" data-testid="assistant-skills-all" onClick={() => setActive("skills")} className={ROW_BUTTON}>
              <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">
                {skills.isLoading ? t("common.loading") : t("sidebar.skills_all")}
              </span>
              <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            </button>
          </Group>
        </div>
      )}

      <Suspense fallback={null}>
        {routineId && <AssistantRoutineDialog agentId={ASSISTANT_ID} routineId={routineId} onClose={() => setRoutineId(null)} />}
        {fileId && <AssistantFileDialog fileId={fileId} onClose={() => setFileId(null)} />}
      </Suspense>
    </aside>
  );
}
