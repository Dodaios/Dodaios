/**
 * Memory & learning: what the agent keeps about the person and its work, and
 * the review queue of what it learned or proposed since. Every queued item
 * shows a diff-style preview and is decided in one click; "Review in chat"
 * puts a ready message into the agent's composer (never sent by itself), so
 * the agent can walk the person through the list in conversation instead.
 */
import { useState } from "react";
import { Check, X } from "lucide-react";

import { useRunLocale } from "@/components/runs/format";
import { useLocaleChunk, useT } from "@/i18n";

import { useAgentSkills } from "../../cardData";
import type { SocietyAgent } from "../../data";
import { useAgentKnowledge } from "../AgentKnowledge";
import type { PanePage } from "./paneState";
import { useDecideReviewItem, type ReviewItem, type ReviewQueue } from "./reviewQueue";
import { seedAgentComposer } from "./seedComposer";
import { AnatomyRow, PaneHint, PaneSection } from "./ui";

/** A diff line's words, without its "+ " / "- " mark. */
function lineText(line: string): string {
  return line.replace(/^[+-]\s?/, "").trim();
}

/** The diff lines that add something the headline does not already say. */
function newLines(preview: readonly string[], headline: string): string[] {
  const said = headline.toLowerCase();
  return preview.filter((line) => {
    const text = lineText(line).toLowerCase();
    return text && !(said && said.includes(text));
  });
}

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
  // Rules it learned on its own, then standing rules the person applied from a proposal.
  const rules = [...new Set([...(knowledge.data?.learned_instructions ?? []), ...(knowledge.data?.applied_rules ?? [])])];

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
            {/* Under the cards, not beside the heading: the count in the heading always fits. */}
            <button type="button" className="ap-link self-start" onClick={reviewInChat} data-testid="agent-pane-review-in-chat">
              {t("society.agent_pane.review_in_chat")}
            </button>
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
  // The proposal is said once: its headline, then only what the diff adds, one line until opened.
  const headline = item.kind === "proposal" ? item.summary : "";
  const extra = newLines(item.preview, headline);
  const lines = open ? extra : extra.slice(0, 1);

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
          <time className="text-[12px] text-muted-foreground" dateTime={new Date(item.created_ms).toISOString()}>
            {new Date(item.created_ms).toLocaleDateString(locale, { day: "2-digit", month: "short" })}
          </time>
        ) : null}
      </div>
      {headline ? <p className="ap-review-text">{headline}</p> : null}
      {lines.length ? (
        <div className="ap-review-lines">
          {lines.map((line, i) => (
            <p key={i} className="ap-review-line" data-op={line.startsWith("+") ? "+" : line.startsWith("-") ? "-" : " "}>
              {lineText(line)}
            </p>
          ))}
        </div>
      ) : null}
      {extra.length > 1 ? (
        <button type="button" className="ap-link self-start" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          {open ? t("society.agent_pane.show_less") : t("society.agent_pane.more_lines").replace("{0}", String(extra.length - 1))}
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
