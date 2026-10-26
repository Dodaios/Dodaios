/**
 * Memory & learning: what the agent keeps about the person and its work, and
 * the review queue of what it learned or proposed since. Every queued item
 * shows a diff-style preview and is decided in one click; "Review in chat"
 * puts a ready message into the agent's composer (never sent by itself), so
 * the agent can walk the person through the list in conversation instead.
 */
import { useState } from "react";
import { BookUser, Check, FileText, MessageSquare, NotebookPen, Sparkles, X } from "lucide-react";

import { useRunLocale } from "@/components/runs/format";
import { useLocaleChunk, useT } from "@/i18n";

import { useAgentSkills } from "../../cardData";
import type { SocietyAgent } from "../../data";
import { useAgentKnowledge } from "../AgentKnowledge";
import type { PanePage } from "./paneState";
import { useDecideReviewItem, type ReviewItem, type ReviewQueue } from "./reviewQueue";
import { seedAgentComposer } from "./seedComposer";
import { AnatomyRow, PaneHint, PaneSection } from "./ui";

/** Preview lines shown before the item is opened. */
const PREVIEW_LINES = 3;

export function MemoryTab({
  agent,
  sample,
  queue,
  queueLoading,
  onPage,
}: {
  agent: SocietyAgent;
  sample: boolean;
  queue: ReviewQueue | undefined;
  queueLoading: boolean;
  onPage: (page: PanePage) => void;
}) {
  const t = useT();
  useLocaleChunk("society");
  const knowledge = useAgentKnowledge(agent.agentId, sample);
  const skills = useAgentSkills(sample ? null : agent.agentId);
  const [seeded, setSeeded] = useState(false);
  const items = queue?.items ?? [];
  const files = knowledge.data?.files ?? [];
  const rules = knowledge.data?.learned_instructions ?? [];

  const reviewInChat = () => {
    setSeeded(seedAgentComposer(agent, t("society.agent_pane.review_chat_seed")));
  };

  return (
    <div className="ap-body" data-testid="agent-pane-memory">
      <PaneSection
        title={
          items.length
            ? t("society.agent_pane.review_title_count").replace("{0}", String(queue?.total ?? items.length))
            : t("society.agent_pane.review_title")
        }
        action={
          items.length ? (
            <button type="button" className="ap-link" onClick={reviewInChat} data-testid="agent-pane-review-in-chat">
              <MessageSquare className="h-3 w-3" aria-hidden />
              {t("society.agent_pane.review_in_chat")}
            </button>
          ) : null
        }
        testId="agent-pane-review"
      >
        {seeded ? <PaneHint>{t("society.agent_pane.review_seeded")}</PaneHint> : null}
        {sample ? (
          <PaneHint>{t("society.profile_card.sample_hint")}</PaneHint>
        ) : queueLoading && !queue ? (
          <PaneHint>{t("society.profile_card.loading")}</PaneHint>
        ) : items.length === 0 ? (
          <PaneHint>{t("society.agent_pane.review_empty")}</PaneHint>
        ) : (
          <div className="flex flex-col gap-2">
            {items.map((item) => (
              <ReviewRow key={item.id} agentId={agent.agentId} item={item} />
            ))}
          </div>
        )}
      </PaneSection>

      <PaneSection title={t("society.profile_card.learned_instructions")}>
        {rules.length ? (
          <ul className="flex list-disc flex-col gap-1.5 pl-4 text-[13px] leading-snug">
            {rules.map((rule) => <li key={rule}>{rule}</li>)}
          </ul>
        ) : (
          <PaneHint>{t("society.profile_card.no_instructions")}</PaneHint>
        )}
      </PaneSection>

      <PaneSection title={t("society.agent_pane.memory_files")}>
        {sample ? (
          <PaneHint>{t("society.profile_card.sample_hint")}</PaneHint>
        ) : knowledge.isLoading ? (
          <PaneHint>{t("society.profile_card.loading")}</PaneHint>
        ) : knowledge.isError ? (
          <p role="alert" className="text-xs text-destructive">{t("society.profile_card.load_error")}</p>
        ) : files.length === 0 ? (
          <PaneHint>{t("society.profile_card.empty")}</PaneHint>
        ) : (
          <div className="ap-rows">
            {files.map((file) => (
              <AnatomyRow
                key={file.path}
                icon={file.name === "USER.md" ? BookUser : file.name === "MEMORY.md" ? NotebookPen : file.kind === "skills" ? Sparkles : FileText}
                label={file.name === "USER.md" ? t("society.profile_card.user_book") : file.name === "MEMORY.md" ? t("society.profile_card.memory_book") : file.name}
                detail={file.path}
                onOpen={() => onPage({ id: `file:${file.path}`, title: file.name })}
                testId={`agent-pane-file-${file.path}`}
              />
            ))}
          </div>
        )}
        <PaneHint>{t("society.profile_card.knowledge_hint")}</PaneHint>
      </PaneSection>

      <PaneSection
        title={t("society.agent_pane.skills")}
        action={
          (skills.data?.length ?? 0) > 0 ? (
            <button type="button" className="ap-link" onClick={() => onPage({ id: "skills", title: t("society.agent_pane.skills") })}>
              {t("society.agent_pane.open")}
            </button>
          ) : null
        }
      >
        <PaneHint>
          {(skills.data?.length ?? 0) > 0
            ? (skills.data ?? []).map((s) => s.name).join(", ")
            : t("society.agent_pane.skills_none")}
        </PaneHint>
      </PaneSection>
    </div>
  );
}

const KIND_KEYS: Record<string, string> = {
  rule: "society.agent_pane.kind_rule",
  skill: "society.agent_pane.kind_skill",
  routine: "society.agent_pane.kind_routine",
  approval_rule: "society.agent_pane.kind_approval_rule",
  focus: "society.agent_pane.kind_focus",
  team: "society.agent_pane.kind_team",
  identity: "society.agent_pane.kind_identity",
};

function ReviewRow({ agentId, item }: { agentId: string; item: ReviewItem }) {
  const t = useT();
  const locale = useRunLocale();
  const decide = useDecideReviewItem(agentId);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const kind =
    item.kind === "proposal"
      ? t(KIND_KEYS[item.proposal_kind] ?? "society.agent_pane.kind_rule")
      : item.kind === "memory_share"
        ? t("society.agent_pane.kind_share")
        : item.book === "USER.md"
          ? t("society.agent_pane.kind_user_memory")
          : t("society.agent_pane.kind_memory");
  const approveLabel =
    item.kind === "proposal" ? t("society.agent_pane.apply") : item.kind === "memory_share" ? t("society.agent_pane.share") : t("society.agent_pane.keep");
  const rejectLabel =
    item.kind === "proposal" ? t("society.agent_pane.reject") : item.kind === "memory_share" ? t("society.agent_pane.keep_private") : t("society.agent_pane.forget");
  const lines = open ? item.preview : item.preview.slice(0, PREVIEW_LINES);

  const run = async (approve: boolean) => {
    setBusy(true);
    setError("");
    try {
      await decide(item, approve);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  return (
    <article className="ap-review" data-testid={`agent-pane-review-${item.id}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="ap-review-kind">{kind}</span>
        {item.created_ms ? (
          <time className="text-[11px] text-muted-foreground" dateTime={new Date(item.created_ms).toISOString()}>
            {new Date(item.created_ms).toLocaleDateString(locale, { day: "2-digit", month: "short" })}
          </time>
        ) : null}
      </div>
      {item.kind === "proposal" ? <p className="ap-review-text">{item.summary}</p> : null}
      {lines.length ? (
        <button
          type="button"
          className="ap-diff text-left"
          data-open={open ? "true" : undefined}
          aria-expanded={item.preview.length > PREVIEW_LINES ? open : undefined}
          onClick={() => setOpen((v) => !v)}
        >
          {lines.map((line, i) => (
            <span key={i} data-op={line.startsWith("+") ? "+" : line.startsWith("-") ? "-" : " "}>
              {line}
            </span>
          ))}
          {!open && item.preview.length > PREVIEW_LINES ? (
            <span>{t("society.agent_pane.more_lines").replace("{0}", String(item.preview.length - PREVIEW_LINES))}</span>
          ) : null}
        </button>
      ) : null}
      {item.reason ? <p className="ap-hint">{item.reason}</p> : null}
      {error ? <p role="alert" className="text-xs text-destructive">{error}</p> : null}
      <div className="flex items-center justify-end gap-1.5">
        <button type="button" className="ap-btn" data-variant="ghost" disabled={busy} onClick={() => void run(false)} data-testid={`agent-pane-review-reject-${item.id}`}>
          <X className="h-3.5 w-3.5" aria-hidden />
          {rejectLabel}
        </button>
        <button type="button" className="ap-btn" data-variant="outline" disabled={busy} onClick={() => void run(true)} data-testid={`agent-pane-review-approve-${item.id}`}>
          <Check className="h-3.5 w-3.5" aria-hidden />
          {approveLabel}
        </button>
      </div>
    </article>
  );
}
