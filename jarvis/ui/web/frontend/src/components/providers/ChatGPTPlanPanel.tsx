import { useCallback, useEffect, useState } from "react";
import { Loader2, LogOut, RotateCw } from "lucide-react";
import openaiLogo from "@/assets/providers/openai.svg?url";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useT } from "@/i18n";

type LoginState = "idle" | "pending" | "denied" | "failed";

interface PlanStatus {
  signed_in: boolean;
  account: string;
  plan_enabled: boolean;
  model: string;
  notice_seen: boolean;
  login: LoginState;
  error: string;
  usage_url: string;
}

interface PlanModel {
  slug: string;
  display_name: string;
}

const POLL_MS = 4000;

async function planCall<T>(path: string, method: "GET" | "POST", payload?: unknown): Promise<T> {
  const res = await fetch(`/api/chatgpt-plan/${path}`, {
    method,
    headers: payload === undefined ? undefined : { "Content-Type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`);
  }
  return body as T;
}

/** The ChatGPT logo, drawn in the current text colour so it fits every appearance. */
function ChatGPTMark() {
  return (
    <span
      aria-hidden="true"
      className="inline-block h-3.5 w-3.5 bg-current"
      style={{ maskImage: `url(${openaiLogo})`, WebkitMaskImage: `url(${openaiLogo})`, maskSize: "contain" }}
    />
  );
}

/** Sign in with ChatGPT: turns run on the user's ChatGPT plan. Tokens never reach the page. */
export function ChatGPTPlanPanel() {
  const t = useT();
  const [state, setState] = useState<PlanStatus | null>(null);
  const [models, setModels] = useState<PlanModel[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setState(await planCall<PlanStatus>("status", "GET"));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(id);
  }, [refresh]);

  const connected = Boolean(state?.signed_in && state.plan_enabled);
  useEffect(() => {
    if (!connected) return;
    planCall<{ models: PlanModel[] }>("models", "GET")
      .then((body) => setModels(body.models))
      .catch((e: Error) => setError(e.message));
  }, [connected]);

  const run = async (path: "login" | "reauth" | "logout" | "notice" | "model", payload?: unknown) => {
    setBusy(true);
    try {
      const next = await planCall<PlanStatus>(path, "POST", payload);
      setState(next);
      setError("");
      // The backend opens the consent page in the system browser; its callback lands there too.
      if (path === "logout") setModels([]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const signedIn = Boolean(state?.signed_in);
  const badge = !state
    ? null
    : connected
      ? "connected"
      : state.error
        ? "error"
        : signedIn
          ? "plan_disabled"
          : "not_signed_in";
  return (
    <div data-testid="chatgpt-plan-panel" className="space-y-2 rounded-lg border border-border px-3 py-2.5 text-xs">
      <p className="flex items-center gap-2 text-sm font-medium text-foreground">
        {t("chatgpt_plan.title")}
        {badge && (
          <span
            data-testid="chatgpt-plan-status"
            className={cn(
              "rounded-full px-2 py-0.5 text-xs font-medium",
              badge === "connected"
                ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                : badge === "error"
                  ? "bg-destructive/[0.12] text-destructive"
                  : "bg-amber-500/15 text-amber-700 dark:text-amber-300",
            )}
          >
            {t(`chatgpt_plan.${badge}`)}
          </span>
        )}
      </p>
      {signedIn && state && (
        <p className="text-muted-foreground">
          {t("chatgpt_plan.account")}: <span className="text-foreground">{state.account}</span>
          {" · "}
          {t(state.plan_enabled ? "chatgpt_plan.plan_enabled" : "chatgpt_plan.plan_disabled")}
        </p>
      )}
      {!signedIn && <p className="leading-relaxed text-muted-foreground">{t("chatgpt_plan.hint")}</p>}
      {state?.login === "pending" && <p className="text-muted-foreground">{t("chatgpt_plan.pending")}</p>}
      {state?.login === "denied" && <p className="text-muted-foreground">{t("chatgpt_plan.denied")}</p>}
      {(error || state?.error) && <p className="text-destructive">{error || state?.error}</p>}
      {connected && state && (
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-muted-foreground">
            {t("chatgpt_plan.model")}
            <select
              data-testid="chatgpt-plan-model"
              className="h-7 rounded-md border border-border bg-background px-2 text-xs text-foreground"
              value={state.model}
              disabled={busy || models.length === 0}
              onChange={(e) => void run("model", { slug: e.target.value })}
            >
              {!state.model && <option value="">{t("chatgpt_plan.model_default")}</option>}
              {models.map((m) => (
                <option key={m.slug} value={m.slug}>
                  {m.display_name}
                </option>
              ))}
            </select>
          </label>
          <span className="text-muted-foreground">{t("chatgpt_plan.using")}</span>
          <a
            href={state.usage_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-foreground underline underline-offset-2"
          >
            {t("chatgpt_plan.manage_usage")}
          </a>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {!signedIn && (
          <Button size="sm" disabled={busy} onClick={() => void run("login")}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ChatGPTMark />}
            {t("chatgpt_plan.continue")}
          </Button>
        )}
        {signedIn && (
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void run("reauth")}>
            <RotateCw className="h-3.5 w-3.5" />
            {t("chatgpt_plan.reauth")}
          </Button>
        )}
        {signedIn && (
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void run("logout")}>
            <LogOut className="h-3.5 w-3.5" />
            {t("chatgpt_plan.logout")}
          </Button>
        )}
      </div>
      {connected && state && !state.notice_seen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="chatgpt-plan-notice-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
        >
          <div className="w-full max-w-sm space-y-3 rounded-xl border border-border bg-background p-5 shadow-lg">
            <p id="chatgpt-plan-notice-title" className="text-sm font-medium text-foreground">
              {t("chatgpt_plan.notice_title")}
            </p>
            <p className="text-xs leading-relaxed text-muted-foreground">{t("chatgpt_plan.notice_body")}</p>
            <div className="flex justify-end">
              <Button size="sm" disabled={busy} onClick={() => void run("notice")}>
                {t("chatgpt_plan.notice_ok")}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
