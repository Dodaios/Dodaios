/**
 * The first conversation: right after setup, the lead conversation opens
 * with the assistant introducing itself and asking three things, one at a
 * time — what to call the person, what they want help with, and which
 * accounts to connect. Answers are tappable chips, an inline field, and
 * Connect buttons in the conversation itself; each answer is saved the
 * moment it is given (`firstConversationApi.ts`). When nothing can answer
 * yet, a fourth line offers a free local model.
 *
 * It is the last act of the one first run, not a second onboarding: the
 * setup window names the assistant and connects an AI, the walk shows the
 * app, and this asks about the person. The backend makes it due only when
 * setup completes with this build, so existing installs never see it, and
 * "Skip" (or finishing) ends it for good. It never speaks: it is text on the
 * page, and the assistant stays silent until it is called.
 */
import { Check, Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAgentChat } from "@/components/agentchat/AgentChatStoreContext";
import { ToolChoiceIcon } from "@/components/agentchat/ToolChoiceChips";
import type { ToolChoice } from "@/components/agentchat/toolChoices";
import { PetMark } from "@/components/pets/PetMark";
import { Button } from "@/components/ui/button";
import { fill, useLocaleChunk, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { joinProviderOptions } from "@/store/agentChat";
import { useEventStore } from "@/store/events";
import { LocalModelQuickstart } from "../localModel/LocalModelQuickstart";
import {
  HELP_TOPICS,
  loadAccountCatalog,
  pollAccountConnect,
  startAccountConnect,
  suggestedAccounts,
  type CatalogAccount,
} from "./accounts";
import {
  cleanName,
  finishFirstConversation,
  firstConversationDue,
  saveHelpTopics,
  saveUserName,
} from "./firstConversationApi";

type Stage = "name" | "help" | "accounts" | "model" | "done";

const POLL_MS = 2_500;
const GIVE_UP_MS = 10 * 60_000;

/**
 * Shows the introduction while it is due, else `fallback` (the front page's
 * greeting on an empty conversation, nothing under a running one).
 */
export function FirstConversation({ fallback = null }: { fallback?: ReactNode }) {
  const [due, setDue] = useState<boolean | null>(null);
  const ready = useLocaleChunk("onboarding");
  useEffect(() => {
    let live = true;
    void firstConversationDue().then((value) => {
      if (live) setDue(value);
    });
    return () => {
      live = false;
    };
  }, []);
  if (due !== true || !ready) return <>{fallback}</>;
  // On the empty page it stands where the greeting stood and scrolls on its
  // own; under a running conversation the conversation's scroll carries it.
  return <Introduction onClose={() => setDue(false)} ownScroll={fallback !== null} />;
}

export default FirstConversation;

function AssistantLine({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <div className="flex items-start gap-3" data-testid={testId}>
      <PetMark size={28} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1 space-y-3 text-base leading-relaxed text-foreground">{children}</div>
    </div>
  );
}

function UserLine({ children }: { children: ReactNode }) {
  return (
    <div className="flex justify-end" data-testid="first-conversation-answer">
      <p className="max-w-[80%] rounded-2xl bg-secondary px-4 py-2 text-base text-foreground">{children}</p>
    </div>
  );
}

function Chip({
  pressed,
  onClick,
  children,
  testId,
}: {
  pressed?: boolean;
  onClick: () => void;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      data-testid={testId}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-sm transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        pressed
          ? "border-accent bg-accent/10 text-foreground"
          : "border-border text-muted-foreground hover:border-border-strong hover:text-foreground",
      )}
    >
      {pressed && <Check className="h-3.5 w-3.5" aria-hidden />}
      {children}
    </button>
  );
}

function QuietButton({ onClick, children, testId }: { onClick: () => void; children: ReactNode; testId?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testId}
      className="rounded text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {children}
    </button>
  );
}

function Introduction({ onClose, ownScroll }: { onClose: () => void; ownScroll: boolean }) {
  const t = useT();
  const queryClient = useQueryClient();
  const assistantName = useEventStore((s) => s.assistantName);
  const catalog = useAgentChat((s) => s.catalog);
  const connections = useAgentChat((s) => s.connections);
  // A key or a subscription that can answer. Keyless local rows do not
  // count: an installed-but-empty Ollama answers nothing yet.
  const canAnswer = useMemo(
    () => (catalog ? joinProviderOptions(catalog.providers, connections).some((p) => p.connected && !p.keyless) : true),
    [catalog, connections],
  );

  const [stage, setStage] = useState<Stage>("name");
  const [nameDraft, setNameDraft] = useState("");
  const [name, setName] = useState<string | null>(null);
  const [topics, setTopics] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [helpAnswer, setHelpAnswer] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [stage]);

  const skipAll = useCallback(() => {
    void finishFirstConversation("skipped");
    onClose();
  }, [onClose]);

  const submitName = async (skip: boolean) => {
    const cleaned = skip ? "" : cleanName(nameDraft);
    if (cleaned) {
      setSaving(true);
      await saveUserName(cleaned);
      setSaving(false);
      void queryClient.invalidateQueries({ queryKey: ["profile"] });
    }
    setName(cleaned || "");
    setStage("help");
  };

  const submitHelp = async (skip: boolean) => {
    const chosen = skip ? [] : HELP_TOPICS.filter((topic) => topics.includes(topic.id));
    const extra = skip ? "" : note.trim();
    if (chosen.length || extra) {
      setSaving(true);
      await saveHelpTopics(chosen.map((topic) => topic.memory), extra);
      setSaving(false);
    }
    const labels = chosen.map((topic) => t(`first_run.conversation.topics.${topic.id}`));
    if (extra) labels.push(extra);
    setHelpAnswer(labels.length ? labels.join(", ") : "");
    setStage("accounts");
  };

  const finish = useCallback(() => {
    void finishFirstConversation("done");
    setStage("done");
  }, []);

  const afterAccounts = () => (canAnswer ? finish() : setStage("model"));

  const greetingName = name ? fill(t("first_run.conversation.nice_to_meet"), { user: name }) : "";

  return (
    <section
      aria-label={t("first_run.conversation.label")}
      data-testid="first-conversation"
      data-stage={stage}
      className={cn(
        "flex w-full max-w-[640px] flex-col gap-5 py-2",
        ownScroll && "max-h-[calc(100vh-240px)] overflow-y-auto",
      )}
    >
      <div className="flex justify-end">
        {stage !== "done" && (
          <QuietButton onClick={skipAll} testId="first-conversation-skip">
            {t("first_run.conversation.skip_all")}
          </QuietButton>
        )}
      </div>

      <AssistantLine testId="first-conversation-hello">
        <p>{fill(t("first_run.conversation.hello"), { name: assistantName || t("first_run.conversation.assistant_fallback") })}</p>
        <p>{t("first_run.conversation.ask_name")}</p>
        {stage === "name" && (
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              void submitName(false);
            }}
          >
            <input
              autoFocus
              value={nameDraft}
              onChange={(event) => setNameDraft(event.target.value)}
              maxLength={60}
              aria-label={t("first_run.conversation.name_label")}
              placeholder={t("first_run.conversation.name_placeholder")}
              data-testid="first-conversation-name"
              className="h-9 min-w-0 flex-1 rounded-lg border border-border bg-background px-3 text-base text-foreground placeholder:text-faint-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <Button type="submit" size="sm" disabled={!cleanName(nameDraft) || saving} data-testid="first-conversation-name-save">
              {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
              {t("first_run.continue")}
            </Button>
            <QuietButton onClick={() => void submitName(true)} testId="first-conversation-name-skip">
              {t("first_run.conversation.skip_question")}
            </QuietButton>
          </form>
        )}
      </AssistantLine>

      {name !== null && <UserLine>{name || t("first_run.conversation.skipped_answer")}</UserLine>}

      {name !== null && (
        <AssistantLine testId="first-conversation-help">
          <p>
            {greetingName && `${greetingName} `}
            {t("first_run.conversation.ask_help")}
          </p>
          {stage === "help" && (
            <>
              <div className="flex flex-wrap gap-2" role="group" aria-label={t("first_run.conversation.ask_help")}>
                {HELP_TOPICS.map((topic) => (
                  <Chip
                    key={topic.id}
                    pressed={topics.includes(topic.id)}
                    testId={`first-conversation-topic-${topic.id}`}
                    onClick={() =>
                      setTopics((prev) => (prev.includes(topic.id) ? prev.filter((id) => id !== topic.id) : [...prev, topic.id]))
                    }
                  >
                    {t(`first_run.conversation.topics.${topic.id}`)}
                  </Chip>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  maxLength={300}
                  aria-label={t("first_run.conversation.other_label")}
                  placeholder={t("first_run.conversation.other_placeholder")}
                  data-testid="first-conversation-other"
                  className="h-9 min-w-0 flex-1 rounded-lg border border-border bg-background px-3 text-sm text-foreground placeholder:text-faint-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
                <Button
                  type="button"
                  size="sm"
                  disabled={(topics.length === 0 && !note.trim()) || saving}
                  onClick={() => void submitHelp(false)}
                  data-testid="first-conversation-help-save"
                >
                  {t("first_run.continue")}
                </Button>
                <QuietButton onClick={() => void submitHelp(true)} testId="first-conversation-help-skip">
                  {t("first_run.conversation.skip_question")}
                </QuietButton>
              </div>
            </>
          )}
        </AssistantLine>
      )}

      {helpAnswer !== null && <UserLine>{helpAnswer || t("first_run.conversation.skipped_answer")}</UserLine>}

      {helpAnswer !== null && (
        <AssistantLine testId="first-conversation-accounts">
          <p>{t("first_run.conversation.ask_accounts")}</p>
          {stage === "accounts" && <AccountsStep topics={topics} onDone={afterAccounts} />}
        </AssistantLine>
      )}

      {(stage === "model" || (stage === "done" && !canAnswer)) && (
        <AssistantLine testId="first-conversation-model">
          <p>{t("first_run.conversation.ask_model")}</p>
          {stage === "model" && (
            <>
              <LocalModelQuickstart onReady={() => finish()} />
              <QuietButton onClick={finish} testId="first-conversation-model-later">
                {t("first_run.conversation.model_later")}
              </QuietButton>
            </>
          )}
        </AssistantLine>
      )}

      {stage === "done" && (
        <AssistantLine testId="first-conversation-done">
          <p>{name ? fill(t("first_run.conversation.done_named"), { user: name }) : t("first_run.conversation.done")}</p>
          <div>
            <Button type="button" size="sm" onClick={onClose} data-testid="first-conversation-close">
              {t("first_run.conversation.start")}
            </Button>
          </div>
        </AssistantLine>
      )}
      <div ref={endRef} aria-hidden />
    </section>
  );
}

type AccountPhase = "idle" | "waiting" | "connected" | "page" | "failed";

function accountRow(account: CatalogAccount): ToolChoice {
  return {
    id: `plugin:${account.id}`,
    label: account.display_name ?? account.id,
    description: "",
    category: "plugins",
    group: "",
    brand: account.id,
    available: false,
    tool_names: [],
    skill: "",
  };
}

function AccountsStep({ topics, onDone }: { topics: string[]; onDone: () => void }) {
  const t = useT();
  const setActiveSection = useEventStore((s) => s.setActiveSection);
  const [accounts, setAccounts] = useState<CatalogAccount[] | null>(null);
  const [phases, setPhases] = useState<Record<string, AccountPhase>>({});
  const timers = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    let live = true;
    void loadAccountCatalog().then((catalog) => {
      if (!live) return;
      const offered = suggestedAccounts(topics, catalog);
      setAccounts(offered);
      setPhases(Object.fromEntries(offered.filter((a) => a.status === "connected").map((a) => [a.id, "connected" as const])));
    });
    const pending = timers.current;
    return () => {
      live = false;
      for (const timer of pending.values()) window.clearTimeout(timer);
    };
  }, [topics]);

  const setPhase = (id: string, phase: AccountPhase) => setPhases((prev) => ({ ...prev, [id]: phase }));

  const connect = async (account: CatalogAccount) => {
    setPhase(account.id, "waiting");
    const started = await startAccountConnect(account.id).catch(() => ({ kind: "page" as const }));
    if (started.kind === "page") {
      setPhase(account.id, "page");
      return;
    }
    const begun = Date.now();
    const tick = async () => {
      timers.current.delete(account.id);
      const state = await pollAccountConnect(account.id, started.flowId).catch(() => "waiting" as const);
      if (state === "connected" || state === "failed") {
        setPhase(account.id, state);
        return;
      }
      if (Date.now() - begun > GIVE_UP_MS) {
        setPhase(account.id, "failed");
        return;
      }
      timers.current.set(account.id, window.setTimeout(() => void tick(), POLL_MS));
    };
    timers.current.set(account.id, window.setTimeout(() => void tick(), POLL_MS));
  };

  if (accounts === null) return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden />;

  return (
    <div className="space-y-3">
      {accounts.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("first_run.conversation.accounts_none")}</p>
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2">
          {accounts.map((account) => {
            const phase = phases[account.id] ?? "idle";
            return (
              <li
                key={account.id}
                data-testid={`first-conversation-account-${account.id}`}
                data-phase={phase}
                className="flex items-center gap-2.5 rounded-lg border border-border px-3 py-2"
              >
                <ToolChoiceIcon row={accountRow(account)} size={22} />
                <span className="min-w-0 flex-1 truncate text-sm text-foreground">{account.display_name ?? account.id}</span>
                {phase === "connected" ? (
                  <span className="inline-flex items-center gap-1 text-xs text-foreground">
                    <Check className="h-3.5 w-3.5" aria-hidden />
                    {t("first_run.conversation.account_connected")}
                  </span>
                ) : phase === "waiting" ? (
                  <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                    {t("first_run.conversation.account_waiting")}
                  </span>
                ) : phase === "page" ? (
                  <QuietButton onClick={() => setActiveSection("plugins")} testId={`first-conversation-account-open-${account.id}`}>
                    {t("first_run.conversation.account_open_plugins")}
                  </QuietButton>
                ) : (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => void connect(account)}
                    data-testid={`first-conversation-account-connect-${account.id}`}
                  >
                    {phase === "failed" ? t("first_run.local_model.retry") : t("first_run.conversation.account_connect")}
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <div className="flex items-center gap-3">
        <Button type="button" size="sm" onClick={onDone} data-testid="first-conversation-accounts-done">
          {t("first_run.continue")}
        </Button>
        <span className="text-xs text-muted-foreground">{t("first_run.conversation.accounts_later")}</span>
      </div>
    </div>
  );
}
