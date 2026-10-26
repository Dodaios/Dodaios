import { memo, useId, useRef, useState, type FormEvent } from "react";
import { KeyRound, ShieldCheck, X } from "lucide-react";
import { fill, useT } from "@/i18n";
import { AgentChatApiError, declineAgentChatCredential, submitAgentChatCredential, type CredentialResult } from "@/lib/agentChatApi";
import { useAgentChat } from "./AgentChatStoreContext";
import { ActionCard } from "./actionCard/ActionCard";
import type { CredentialState } from "./reduce";

/**
 * An agent's secure credential field (dodaios/agent_chat/credential_requests.py).
 *
 * The person pastes a token the agent asked for; the value goes from this
 * field to the agent's vault in one request and is never kept in the chat:
 * no event, no store and no reply carries it. The agent only learns that the
 * environment variable is set.
 */

export const CredentialCard = memo(function CredentialCard({ credential }: { credential: CredentialState }) {
  const t = useT();
  const descriptionId = useId();
  const agent = credential.asker || t("credential_card.fallback_agent");
  return (
    <div className="my-2 w-full max-w-2xl space-y-3">
      <p id={descriptionId} className="whitespace-pre-wrap text-sm leading-6 text-foreground [overflow-wrap:anywhere]">
        {credential.description || fill(t("credential_card.subtitle"), { agent, env: credential.env })}
      </p>
      {credential.status !== null ? <ClosedCard credential={credential} /> : (
        <OpenCard key={credential.requestId} credential={credential} descriptionId={descriptionId} />
      )}
    </div>
  );
});

function OpenCard({ credential, descriptionId }: { credential: CredentialState; descriptionId: string }) {
  const t = useT();
  const sessionId = useAgentChat((s) => s.activeSessionId);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resolved, setResolved] = useState<CredentialResult["status"] | null>(null);
  const errorId = useId();
  const sending = useRef(false);
  const agent = credential.asker || t("credential_card.fallback_agent");

  const failure = (err: unknown): string => {
    if (err instanceof AgentChatApiError) {
      const keys: Record<string, string> = {
        invalid_token: "invalid_token", network_error: "network_error", validation_timeout: "validation_timeout",
        storage_failed: "storage_failed", request_busy: "request_busy", request_closed: "expired",
      };
      const key = keys[err.code];
      if (key) return t(`credential_card.${key}`);
    }
    if (err instanceof AgentChatApiError && (err.status === 400 || err.status === 422)) return t("credential_card.invalid");
    if (err instanceof AgentChatApiError && (err.status === 404 || err.status === 410)) return t("credential_card.expired");
    if (err instanceof TypeError) return t("credential_card.network_error");
    return t("credential_card.failed");
  };

  const run = async (action: (sid: string) => Promise<CredentialResult>, expected: CredentialResult["status"]) => {
    if (sending.current || !sessionId) return;
    sending.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await action(sessionId);
      if (!result.ok || result.status !== expected || result.request_id !== credential.requestId) {
        throw new AgentChatApiError("credential-unconfirmed", 502);
      }
      setValue("");
      // The HTTP receipt is sufficient even while the event stream reconnects.
      setResolved(result.status);
    } catch (err) {
      setError(failure(err));
      sending.current = false;
      setBusy(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const secret = value.trim();
    if (secret) void run((sid) => submitAgentChatCredential(sid, credential.requestId, secret), "saved");
  };

  if (resolved) return <ClosedCard credential={{ ...credential, status: resolved }} />;

  // The shared action card frame: the source says a secure field is asking,
  // the field and its two answers sit where every card keeps its actions.
  return (
    <ActionCard
      id={`credential:${credential.requestId}`}
      testId="credential-card"
      state="open"
      source={{ icon: <KeyRound strokeWidth={1.75} />, label: t("action_card.source.secure_field") }}
      title={credential.label}
      ariaLabel={t("credential_card.aria")}
      lines={credential.replace ? [fill(t("credential_card.replace_note"), { agent })] : undefined}
      trailing={
        <button
          type="button"
          onClick={() => void run((sid) => declineAgentChatCredential(sid, credential.requestId), "declined")}
          disabled={busy}
          aria-label={t("credential_card.decline")}
          title={t("credential_card.decline")}
          className="action-card-dismiss"
        >
          <X aria-hidden className="h-4 w-4" />
        </button>
      }
    >
      <form onSubmit={submit} aria-describedby={descriptionId} className="flex flex-col gap-2 sm:flex-row">
        <input
          type="password"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          disabled={busy}
          autoComplete="new-password"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={false}
          data-1p-ignore
          data-lpignore="true"
          name={`credential-${credential.requestId}`}
          maxLength={16384}
          placeholder={credential.placeholder || fill(t("credential_card.placeholder"), { label: credential.label })}
          aria-label={credential.label}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${descriptionId} ${errorId}` : descriptionId}
          className="h-[34px] min-w-0 flex-1 rounded-lg border border-border bg-background px-3 text-sm text-foreground placeholder:text-muted-foreground focus-visible:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={busy || !value.trim()}
          className="action-card-button h-[34px] justify-center"
          data-tone="primary"
        >
          {busy ? t("credential_card.saving") : t("credential_card.save")}
        </button>
      </form>
      <div className="mt-2.5 space-y-0.5 text-xs leading-5 text-muted-foreground">
        <p className="m-0 flex items-center gap-1.5">
          <ShieldCheck aria-hidden className="h-3.5 w-3.5 shrink-0" />
          <span>{t("credential_card.footer")}</span>
        </p>
        <p className="m-0">{t("credential_card.stays_open")}</p>
        {error ? (
          <p id={errorId} role="alert" className="m-0 text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </ActionCard>
  );
}

function ClosedCard({ credential }: { credential: CredentialState }) {
  const t = useT();
  const saved = credential.status === "saved";
  const key = saved ? "saved" : credential.status === "declined" ? "declined" : credential.status === "timeout" ? "timeout" : "cancelled";
  const sentence = fill(t(`credential_card.${key}`), { label: credential.label, env: credential.env });
  return (
    <ActionCard
      id={`credential:${credential.requestId}`}
      testId="credential-card"
      state={credential.status ?? ""}
      source={{ icon: <KeyRound strokeWidth={1.75} />, label: t("action_card.source.secure_field") }}
      title={credential.label}
      ariaLabel={sentence}
      settled={{ tone: saved ? "success" : "muted", label: sentence }}
    />
  );
}
