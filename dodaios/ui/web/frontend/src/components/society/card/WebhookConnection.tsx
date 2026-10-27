import { ProviderVerification } from "./ProviderVerification";
import { useState, type ReactNode } from "react";
import { Check, Copy, Eye, EyeOff, KeyRound, Link2, RotateCw, TerminalSquare } from "lucide-react";
import { useLocaleChunk, useT } from "@/i18n";
import { cn } from "@/lib/utils";

type Connection = { path: string; token: string; provider?: string; configured?: boolean; oidc_audience?: string; service_account?: string };

const MASK = "•".repeat(20);

const ICON = "shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground";

function CopyButton({ label, copiedLabel, done, onCopy }: { label: string; copiedLabel: string; done: boolean; onCopy: () => void }) {
  return <button type="button" className={ICON} onClick={onCopy} aria-label={label} title={done ? copiedLabel : undefined}>
    {done ? <Check size={13} className="text-success" /> : <Copy size={13} />}
  </button>;
}

function Row({ glyph, title, help, children }: { glyph: ReactNode; title: string; help: string; children: ReactNode }) {
  return <div className="space-y-1">
    <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">{glyph}{title}</div>
    <div className="flex items-center gap-1 rounded-lg border border-border bg-background px-2 py-1">{children}</div>
    <p className="text-xs leading-snug text-faint-foreground">{help}</p>
  </div>;
}

/**
 * A webhook routine's connection: the URL to POST to, its key (masked until
 * revealed) and a ready header line, each with copy and one line of help.
 * Credentials stay in this UI's memory, never in chat or the routine spec.
 */
export function WebhookConnection({ taskId }: { taskId: string }) {
  const t = useT();
  const ready = useLocaleChunk("society");
  const [connection, setConnection] = useState<Connection | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState<"url" | "token" | "header" | null>(null);
  const [revealed, setRevealed] = useState(false);
  const own = (key: string) => t(`society.agent_routines.webhook.${key}`);

  const load = async (rotate = false) => {
    if (rotate && !window.confirm(t("society.hooks.rotate_confirm"))) return;
    setBusy(true);
    setError("");
    setCopied(null);
    try {
      const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/webhook-connection${rotate ? "/rotate" : ""}`, {
        method: rotate ? "POST" : "GET", cache: "no-store",
      });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`);
      setConnection(body as Connection);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const copy = async (which: "url" | "token" | "header", text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(which);
      window.setTimeout(() => setCopied((current) => (current === which ? null : current)), 1800);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  if (!ready) return null;
  const button = "inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs text-foreground transition-colors hover:bg-secondary disabled:opacity-50";
  const value = "min-w-0 flex-1 truncate bg-transparent font-mono text-xs text-foreground focus:outline-none";
  const href = connection ? new URL(connection.path, window.location.origin).href : "";
  const header = connection ? `Authorization: Bearer ${connection.token}` : "";
  return (
    <div className="mt-2 block space-y-2.5" data-testid="webhook-connection">
      {!connection ? <button type="button" className={button} disabled={busy} onClick={() => void load()}>
        <Link2 size={13} />{t(busy ? "society.hooks.loading" : "society.hooks.connect")}
      </button> : <>
        <Row glyph={<Link2 size={12} />} title={t("society.hooks.endpoint")} help={own("url_help")}>
          <input className={value} readOnly aria-label={t("society.hooks.endpoint")} value={href} onFocus={(e) => e.currentTarget.select()} />
          <CopyButton label={own("copy_url")} copiedLabel={t("society.hooks.copied")} done={copied === "url"} onCopy={() => void copy("url", href)} />
        </Row>
        {connection.provider && !["generic", "github"].includes(connection.provider) ? <ProviderVerification taskId={taskId} provider={connection.provider} configured={connection.configured} audience={connection.oidc_audience} serviceAccount={connection.service_account} /> : <>
          <Row glyph={<KeyRound size={12} />} title={t("society.hooks.token")} help={own("key_help")}>
            <input className={value} type={revealed ? "text" : "password"} readOnly autoComplete="off" aria-label={t("society.hooks.token")} value={connection.token} />
            <button type="button" className={ICON} onClick={() => setRevealed((v) => !v)} aria-label={revealed ? own("hide") : own("reveal")} aria-pressed={revealed}>
              {revealed ? <EyeOff size={13} /> : <Eye size={13} />}
            </button>
            <CopyButton label={t("society.hooks.copy")} copiedLabel={t("society.hooks.copied")} done={copied === "token"} onCopy={() => void copy("token", connection.token)} />
          </Row>
          <Row glyph={<TerminalSquare size={12} />} title={own("header")} help={own("header_help")}>
            <code className={cn(value, "select-all")} data-testid="webhook-header-line">{revealed ? header : `Authorization: Bearer ${MASK}`}</code>
            <CopyButton label={own("copy_header")} copiedLabel={t("society.hooks.copied")} done={copied === "header"} onCopy={() => void copy("header", header)} />
          </Row>
          <span className="flex flex-wrap gap-2">
            <button type="button" className={button} disabled={busy} onClick={() => void load(true)}><RotateCw size={12} />{t("society.hooks.rotate")}</button>
          </span>
          <span className="block text-xs leading-snug text-faint-foreground">{t("society.hooks.auth")}</span>
        </>}
        <span className="block text-xs leading-snug text-faint-foreground">{t("society.hooks.remote")}</span>
      </>}
      {error ? <span role="alert" className="block text-xs text-destructive">{error}</span> : null}
    </div>
  );
}
