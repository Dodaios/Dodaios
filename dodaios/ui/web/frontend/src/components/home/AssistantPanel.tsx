import { lazy, Suspense, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, FileText, Sparkles } from "lucide-react";
import { PanelStatus, usePanelNow } from "@/components/home/PanelStatus";
import { EarlierChatsLink } from "@/components/home/EarlierChatsLink";
import { PanelActivity } from "@/components/home/PanelActivity";
import { PanelComputers } from "@/components/home/PanelComputers";
import { PanelOutputs } from "@/components/home/PanelOutputs";
import { PanelReach } from "@/components/home/PanelReach";
import { ASSISTANT_ID, PanelRoutines } from "@/components/home/PanelRoutines";
import { useVoiceModeSwitch } from "@/components/home/assistantStatus";
import { chatRowLabel, useChatRows } from "@/components/home/chatRows";
import { FOCUS, PANEL_ICON, PANEL_ROW, PANEL_ROW_BUTTON, PanelEmpty, PanelSection } from "@/components/home/panelParts";
import { PetMark } from "@/components/pets/PetMark";
import { Switch } from "@/components/ui/switch";
import { useSetSkillEnabled, useSkillsList } from "@/hooks/useSkills";
import { useVoiceEngineDisplay } from "@/hooks/useVoiceEngineDisplay";
import { useLocaleChunk, useT } from "@/i18n";
import { fetchLeadSession } from "@/lib/agentChatApi";
import { NEUTRAL_ASSISTANT_NAME } from "@/lib/assistantNameCache";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { useSettingsJump } from "@/store/settingsJump";
import { useSoulProfile, type SoulFileId } from "@/views/assistant/api";

// A routine's or a file's own page is only fetched when one is opened.
const AssistantRoutineDialog = lazy(() => import("@/components/home/AssistantRoutineDialog"));
const AssistantFileDialog = lazy(() => import("@/components/home/AssistantFileDialog"));

const RECENTS_SHOWN = 4;
const SKILLS_SHOWN = 8;
const TAB_KEY = "jarvis.sidebar.assistantTab.v1";

type Tab = "activity" | "library";

function readTab(): Tab {
  try {
    return localStorage.getItem(TAB_KEY) === "library" ? "library" : "activity";
  } catch {
    return "activity";
  }
}

/**
 * The one endless conversation: its id, so the list of earlier chats can
 * leave it out, and the computer it runs on ("" = this one).
 */
function useConversation(): { id: string | null; computerId: string } {
  const lead = useQuery({
    queryKey: ["sidebar", "conversation"],
    staleTime: 5 * 60_000,
    retry: false,
    queryFn: async () => {
      const session = await fetchLeadSession();
      return { id: session.session_id ?? null, computerId: session.computer_id ?? "" };
    },
  });
  return lead.data ?? { id: null, computerId: "" };
}

/**
 * The assistant's panel, to the right of its conversation: one card that
 * says who it is, what it is doing, and what it has to show for it.
 *
 * On top its face (the pet the person chose in My Pets, the same one the
 * caption switch and the chat draw), the name the person gave it (from the
 * wake phrase) and one line for what it is doing right now; the pet plays
 * the row that line describes (`usePanelNow`). Face and name lead back to the conversation. Under
 * them the ways to reach it: a call, Slack and Telegram.
 *
 * "Activity" is its work: its routines (the first two, the rest folded away,
 * each with a switch), the computers it can work on (the one it runs on
 * marked), the chats in the Agentic IDE it sent a task to, and the files it
 * made. "Library" is what belongs to it: how it is spoken to, its own files (character, standing instructions,
 * memory, what it knows about the person), its skills and the chats from
 * before.
 */
export default function AssistantPanel({ onConversation }: { onConversation: () => void }) {
  const t = useT();
  useLocaleChunk("society");
  const setActive = useEventStore((s) => s.setActiveSection);
  const profile = useSoulProfile();
  const skills = useSkillsList();
  const setSkillEnabled = useSetSkillEnabled();
  const voice = useVoiceEngineDisplay();
  const { rows, isActive, open: openRow } = useChatRows();
  const conversation = useConversation();
  const assistantName = useEventStore((s) => s.assistantName);
  const call = useVoiceModeSwitch();
  const now = usePanelNow(conversation.id, call.live);
  const [tab, setTab] = useState<Tab>(readTab);
  const [routineId, setRoutineId] = useState<string | null>(null);
  const [fileId, setFileId] = useState<SoulFileId | null>(null);

  const pickTab = (next: Tab) => {
    setTab(next);
    try { localStorage.setItem(TAB_KEY, next); } catch { /* a convenience only */ }
  };

  const openSettings = (group: string) => {
    useSettingsJump.getState().request(group);
    setActive("settings");
  };

  // The conversation itself is the face above, not one of the chats from before.
  const recents = rows.filter((row) => row.id !== conversation.id).slice(0, RECENTS_SHOWN);
  const files = profile.data?.files ?? [];
  const skillRows = [...(skills.data?.skills ?? [])]
    .filter((skill) => skill.state === "active" || skill.state === "disabled")
    .sort((a, b) => Number(b.state === "active") - Number(a.state === "active") || a.name.localeCompare(b.name));
  // The name the person gave the assistant; the product's name while there is none.
  const ownName = assistantName.trim();
  const name = ownName && ownName !== NEUTRAL_ASSISTANT_NAME ? ownName : t("sidebar.conversation");

  return (
    <aside aria-label={name} data-testid="assistant-panel"
      className="flex h-full w-[336px] shrink-0 flex-col overflow-y-auto p-3 scrollbar-jarvis">
      <div className="rounded-xl border border-border bg-card p-3">
        <button type="button" data-testid="assistant-panel-conversation" onClick={onConversation} title={name}
          className={cn("flex w-full min-w-0 items-center gap-3 rounded-lg p-1 text-left", FOCUS)}>
          <PetMark size={48} state={now.pet} className="shrink-0" />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-base font-semibold text-foreground-strong">{name}</span>
            <PanelStatus now={now} />
          </span>
        </button>

        <PanelReach call={call} name={name} />

        <div role="tablist" aria-label={name} className="mt-3 flex items-center gap-1">
          {(["activity", "library"] as const).map((id) => (
            <button key={id} type="button" role="tab" aria-selected={tab === id} data-testid={`assistant-panel-tab-${id}`}
              onClick={() => pickTab(id)}
              className={cn("rounded-md px-2.5 py-1 text-sm font-medium transition-colors", FOCUS,
                tab === id ? "bg-secondary text-foreground-strong" : "text-muted-foreground hover:text-foreground")}>
              {t(`sidebar.tab_${id}`)}
            </button>
          ))}
        </div>

        {tab === "activity" ? (
          <div role="tabpanel" className="mt-3">
            <PanelRoutines onOpen={setRoutineId} />
            <PanelComputers leadComputerId={conversation.computerId} name={name} />
            <PanelActivity name={name} />
            <PanelOutputs name={name} />
          </div>
        ) : (
          <div role="tabpanel" className="mt-3">
            <PanelSection id="voice" title={t("sidebar.voice")}>
              <button type="button" data-testid="assistant-voice-model" onClick={() => openSettings("voice")} className={PANEL_ROW_BUTTON}>
                <span className="shrink-0 text-sm text-foreground">{t("sidebar.voice_model")}</span>
                <span className="min-w-0 flex-1 truncate text-right text-sm text-muted-foreground">{voice.providerLabel}</span>
                <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              </button>
              <button type="button" data-testid="assistant-voice-wake" onClick={() => openSettings("wake-word")} className={PANEL_ROW_BUTTON}>
                <span className="shrink-0 text-sm text-foreground">{t("sidebar.wake_word")}</span>
                <span className="min-w-0 flex-1 truncate text-right text-sm text-muted-foreground">{profile.data?.wake_phrase ?? ""}</span>
                <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              </button>
            </PanelSection>

            <PanelSection id="files" title={t("assistant_view.files_title")}>
              {files.map((file) => (
                <button key={file.id} type="button" data-testid={`assistant-file-${file.id}`} onClick={() => setFileId(file.id)}
                  className={PANEL_ROW_BUTTON}>
                  <FileText aria-hidden strokeWidth={1.75} className={PANEL_ICON} />
                  <span className="min-w-0 flex-1 truncate text-sm text-foreground">{file.filename}</span>
                  <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                </button>
              ))}
              {files.length === 0 && (
                <PanelEmpty>{profile.isLoading ? t("common.loading") : t("sidebar.files_empty")}</PanelEmpty>
              )}
            </PanelSection>

            <PanelSection id="skills" title={t("nav.skills")}>
              {skillRows.slice(0, SKILLS_SHOWN).map((skill) => (
                <div key={skill.name} className={PANEL_ROW}>
                  <Sparkles aria-hidden strokeWidth={1.75} className={PANEL_ICON} />
                  <span title={skill.name} className={cn("min-w-0 flex-1 truncate text-sm", skill.state === "active" ? "text-foreground" : "text-muted-foreground")}>{skill.name}</span>
                  <Switch aria-label={skill.name} data-testid={`assistant-skill-switch-${skill.name}`}
                    checked={skill.state === "active"} disabled={setSkillEnabled.isPending}
                    onCheckedChange={(enabled) => setSkillEnabled.mutate({ name: skill.name, enabled })} />
                </div>
              ))}
              <button type="button" data-testid="assistant-skills-all" onClick={() => setActive("skills")} className={PANEL_ROW_BUTTON}>
                <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">
                  {skills.isLoading ? t("common.loading") : t("sidebar.skills_all")}
                </span>
                <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              </button>
            </PanelSection>

            <PanelSection id="recents" title={t("sidebar.recent_chats")}>
              {recents.map((row) => {
                const label = chatRowLabel(row, t);
                const onStage = isActive(row);
                return (
                  <button key={`${row.kind}:${row.id}`} type="button" data-testid={`assistant-recent-${row.id}`}
                    onClick={() => openRow(row)} title={label.text} aria-current={onStage ? "page" : undefined}
                    className={cn(PANEL_ROW_BUTTON, onStage && "bg-secondary")}>
                    <span className={cn("min-w-0 flex-1 truncate text-sm", label.untitled ? "text-muted-foreground" : "text-foreground")}>{label.text}</span>
                  </button>
                );
              })}
              <EarlierChatsLink />
            </PanelSection>
          </div>
        )}
      </div>

      <Suspense fallback={null}>
        {routineId && <AssistantRoutineDialog agentId={ASSISTANT_ID} routineId={routineId} onClose={() => setRoutineId(null)} />}
        {fileId && <AssistantFileDialog fileId={fileId} onClose={() => setFileId(null)} />}
      </Suspense>
    </aside>
  );
}
