/**
 * The pane's drill-down pages. Each replaces the tab body in place, under a
 * header with Back, so configuring an agent never stacks a modal on its chat.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileText, Sparkles } from "lucide-react";

import { useT } from "@/i18n";

import { useAgentSkills } from "../../cardData";
import { useUpdateAgentConfig, type SocietyAgent } from "../../data";
import { MemoryMarkdown } from "../../chat/MemoryDocument";
import { AgentSandboxSection } from "../AgentSandboxSection";
import { LearnedInstructions } from "../AgentKnowledge";
import { LeadInstructions } from "../LeadSections";
import { PaneHint, PaneSection } from "./ui";

export function InstructionsPage({ agent, sample }: { agent: SocietyAgent; sample: boolean }) {
  const t = useT();
  const update = useUpdateAgentConfig();
  const [draft, setDraft] = useState(agent.description);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  if (agent.tier === "lead") {
    return (
      <div className="ap-body">
        <LeadInstructions />
      </div>
    );
  }
  const dirty = draft !== agent.description;
  const save = async () => {
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      const text = draft.trim();
      await update(agent, { description: text });
      setDraft(text);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="ap-body" data-testid="agent-pane-instructions-page">
      <PaneSection>
        <PaneHint>{t("society.profile_card.instructions_hint")}</PaneHint>
        <textarea
          className="ap-input min-h-[240px]"
          value={draft}
          aria-label={t("society.agent_pane.instructions")}
          placeholder={t("society.card.no_description")}
          disabled={sample || saving}
          onChange={(event) => {
            setDraft(event.target.value);
            setSaved(false);
          }}
          data-testid="agent-pane-instructions-input"
        />
        <div className="flex items-center justify-end gap-2">
          {error ? <span role="alert" className="mr-auto text-xs text-destructive">{error}</span> : null}
          {saved && !dirty ? <span role="status" className="mr-auto text-xs text-muted-foreground">{t("society.profile_card.saved")}</span> : null}
          <button type="button" className="ap-btn" data-variant="ghost" disabled={!dirty || saving} onClick={() => setDraft(agent.description)}>
            {t("society.agent_pane.discard")}
          </button>
          <button type="button" className="ap-btn" data-variant="primary" disabled={!dirty || saving || sample} onClick={() => void save()}>
            {t(saving ? "society.card.saving" : "society.card.save")}
          </button>
        </div>
      </PaneSection>
      <LearnedInstructions agentId={agent.agentId} sample={sample} />
    </div>
  );
}

export function SkillsPage({ agent, sample }: { agent: SocietyAgent; sample: boolean }) {
  const t = useT();
  const skills = useAgentSkills(sample ? null : agent.agentId);
  const rows = skills.data ?? [];
  return (
    <div className="ap-body" data-testid="agent-pane-skills-page">
      <PaneHint>{t("society.agent_pane.skills_hint")}</PaneHint>
      {rows.length === 0 ? (
        <PaneHint>{skills.isLoading ? t("society.profile_card.loading") : t("society.agent_pane.skills_none")}</PaneHint>
      ) : (
        <div className="ap-rows">
          {rows.map((skill) => (
            <div key={skill.slug} className="ap-row items-start">
              <span className="ap-row-icon" aria-hidden><Sparkles className="h-3.5 w-3.5" /></span>
              <span className="min-w-0 flex-1">
                <span className="ap-row-label">{skill.name}</span>
                <span className="block text-xs leading-snug text-muted-foreground">{skill.whenToUse || skill.description}</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function FilesPage({ agent }: { agent: SocietyAgent }) {
  const t = useT();
  const sandbox = agent.executionEnvironment === "sandbox";
  return (
    <div className="ap-body" data-testid="agent-pane-files-page">
      <PaneHint>{t(sandbox ? "society.sandbox.storage" : "society.agent_pane.files_hint")}</PaneHint>
      <div className="ap-rows">
        <div className="ap-row">
          <span className="min-w-0 flex-1">
            <span className="ap-row-label">{t("society.card.workspace")}</span>
            <span className="block break-all font-mono text-[11px] text-muted-foreground">{agent.workspaceDir || `society/${agent.agentId}/workspace`}</span>
          </span>
        </div>
        <div className="ap-row">
          <span className="min-w-0 flex-1">
            <span className="ap-row-label">{t("society.card.wiki")}</span>
            <span className="block break-all font-mono text-[11px] text-muted-foreground">{agent.wikiNamespace || `society/${agent.agentId}/`}</span>
          </span>
        </div>
      </div>
      {sandbox ? <AgentSandboxSection agent={agent} show="files" /> : null}
    </div>
  );
}

/** One memory file, read-only, rendered as the agent wrote it. */
export function MemoryFilePage({ agent, path }: { agent: SocietyAgent; path: string }) {
  const t = useT();
  const file = useQuery({
    queryKey: ["society", "profile-knowledge-file", agent.agentId, path],
    retry: false,
    queryFn: async ({ signal }) => {
      const res = await fetch(
        `/api/society/agents/${encodeURIComponent(agent.agentId)}/knowledge/file?path=${encodeURIComponent(path)}`,
        { signal },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return (await res.json()) as { content: string };
    },
  });
  return (
    <div className="ap-body" data-testid="agent-pane-file-page">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <FileText className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="truncate font-mono">{path}</span>
        <span className="ml-auto shrink-0">{t("society.profile_card.read_only")}</span>
      </div>
      {file.isLoading ? (
        <PaneHint>{t("society.profile_card.loading")}</PaneHint>
      ) : file.isError ? (
        <p role="alert" className="text-xs text-destructive">{t("society.profile_card.load_error")}</p>
      ) : (
        <div className="ap-file">
          <MemoryMarkdown text={file.data?.content || t("society.profile_card.empty_file")} />
        </div>
      )}
    </div>
  );
}
