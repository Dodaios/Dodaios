import { memo, useId, useRef, useState, type FormEvent } from "react";
import { KeyRound, Lock, ShieldCheck } from "lucide-react";
import { fill, useT } from "@/i18n";
import { AgentChatApiError, declineAgentChatCredential, submitAgentChatCredential } from "@/lib/agentChatApi";
import { useAgentChat } from "./AgentChatStoreContext";
import { ChatPopup, ChatPromptButton, ChatPromptCard } from "./ChatPromptCard";
import type { CredentialState } from "./reduce";

/**
 * An agent asks to sign in to a website for the person
 * (dodaios/society/login_tool.py). The card opens a small form; the username
 * and password go from it to the agent's vault in one request and are never
 * kept in the chat. The agent's browser types them only on that site, and the
 * agent itself only ever sees placeholders.
 */
export const LoginCard = memo(function LoginCard({ credential }: { credential: CredentialState }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [resolved, setResolved] = useState<string | null>(null);
  const status = resolved ?? credential.status;
  const site = credential.label;
  const title = fill(t("login_card.title"), { site });
  if (status !== null) {
    const saved = status === "saved";
    return (
      <ChatPromptCard
        testId="login-card"
        tile={<KeyRound aria-hidden className="h-4 w-4" strokeWidth={1.75} />}
        title={title}
        settled={{
          tone: saved ? "success" : "muted",
          label: fill(t(saved ? "login_card.saved" : "login_card.declined"), { site }),
        }}
      />
    );
  }
  return (
    <>
      <ChatPromptCard
        testId="login-card"
        tile={<KeyRound aria-hidden className="h-4 w-4" strokeWidth={1.75} />}
        title={title}
        subtitle={t("login_card.subtitle")}
        action={
          <ChatPromptButton onClick={() => setOpen(true)} testId="login-card-open">
            {t("login_card.open")}
          </ChatPromptButton>
        }
      />
      {open ? (
        <LoginForm credential={credential} onClose={() => setOpen(false)} onDone={(s) => { setResolved(s); setOpen(false); }} />
      ) : null}
    </>
  );
});

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function LoginForm({
  credential,
  onClose,
  onDone,
}: {
  credential: CredentialState;
  onClose: () => void;
  onDone: (status: string) => void;
}) {
  const t = useT();
  const sessionId = useAgentChat((s) => s.activeSessionId);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sending = useRef(false);
  const errorId = useId();
  const agent = credential.asker || t("credential_card.fallback_agent");
  const host = hostOf(credential.url);

  const failure = (err: unknown): string => {
    if (err instanceof AgentChatApiError) {
      if (err.code === "storage_failed") return t("login_card.storage_failed");
      if (err.code === "request_busy") return t("credential_card.request_busy");
      if (err.code === "request_closed" || err.status === 404 || err.status === 410) return t("credential_card.expired");
      if (err.status === 400 || err.status === 422) return t("login_card.invalid");
    }
    if (err instanceof TypeError) return t("credential_card.network_error");
    return t("login_card.failed");
  };

  const run = async (action: (sid: string) => Promise<{ ok: boolean; status: string; request_id: string }>, expected: string) => {
    if (sending.current || !sessionId) return;
    sending.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await action(sessionId);
      if (!result.ok || result.status !== expected || result.request_id !== credential.requestId) {
        throw new AgentChatApiError("credential-unconfirmed", 502);
      }
      setUsername("");
      setPassword("");
      onDone(result.status);
    } catch (err) {
      setError(failure(err));
      sending.current = false;
      setBusy(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!username.trim() || !password) return;
    const body = JSON.stringify({ username: username.trim(), password });
    void run((sid) => submitAgentChatCredential(sid, credential.requestId, body), "saved");
  };

  const field =
    "h-[38px] w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground placeholder:text-muted-foreground focus-visible:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";

  return (
    <ChatPopup
      title={fill(t("login_card.title"), { site: credential.label })}
      tile={<Lock aria-hidden className="h-4 w-4" strokeWidth={1.75} />}
      onClose={onClose}
      testId="login-form"
    >
      {credential.description ? (
        <p className="m-0 mb-3 text-sm leading-6 text-muted-foreground [overflow-wrap:anywhere]">
          {credential.description}
        </p>
      ) : null}
      <form onSubmit={submit} className="flex flex-col gap-2.5" aria-describedby={error ? errorId : undefined}>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          {t("login_card.username")}
          <input
            type="text"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            disabled={busy}
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
            data-1p-ignore
            data-lpignore="true"
            name={`login-user-${credential.requestId}`}
            maxLength={1024}
            className={field}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          {t("login_card.password")}
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={busy}
            autoComplete="new-password"
            data-1p-ignore
            data-lpignore="true"
            name={`login-pass-${credential.requestId}`}
            maxLength={1024}
            className={field}
          />
        </label>
        <p className="m-0 flex items-start gap-1.5 text-xs leading-5 text-muted-foreground">
          <ShieldCheck aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{fill(t("login_card.footer"), { agent, host: host || credential.label })}</span>
        </p>
        {error ? (
          <p id={errorId} role="alert" className="m-0 text-xs text-destructive">
            {error}
          </p>
        ) : null}
        <div className="mt-1 flex items-center justify-between gap-2">
          <button
            type="button"
            onClick={() => void run((sid) => declineAgentChatCredential(sid, credential.requestId), "declined")}
            disabled={busy}
            className="rounded-full px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted disabled:opacity-60"
          >
            {t("login_card.decline")}
          </button>
          <button
            type="submit"
            disabled={busy || !username.trim() || !password}
            className="rounded-full bg-foreground px-4 py-1.5 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {busy ? t("credential_card.saving") : t("login_card.save")}
          </button>
        </div>
      </form>
    </ChatPopup>
  );
}
