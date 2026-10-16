import { useCallback, useEffect, useState } from "react";
import { Loader2, LogIn, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useT } from "@/i18n";

type BridgeStatus =
  | "ready"
  | "login_required"
  | "offline"
  | "session_invalid"
  | "starting"
  | "failed"
  | "not_installed"
  | "not_configured";

interface BridgeState {
  status: BridgeStatus;
  detail: string;
}

const POLL_MS = 4000;

async function bridgeCall(path: string, method: "GET" | "POST"): Promise<BridgeState> {
  const res = await fetch(`/api/chatgpt-web/${path}`, { method });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`);
  }
  return body as BridgeState;
}

/** Status, one-time sign-in and restart for the local ChatGPT web bridge. */
export function ChatGPTBridgePanel() {
  const t = useT();
  const [state, setState] = useState<BridgeState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setState(await bridgeCall("status", "GET"));
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

  const run = async (path: "login" | "restart") => {
    setBusy(true);
    try {
      setState(await bridgeCall(path, "POST"));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const status = state?.status;
  const needsLogin = status === "login_required" || status === "session_invalid";
  return (
    <div data-testid="chatgpt-bridge-panel" className="space-y-2 rounded-lg border border-border px-3 py-2.5 text-xs">
      <p className="flex items-center gap-2 text-sm font-medium text-foreground">
        {t("chatgpt_bridge.title")}
        {status && (
          <span
            data-testid="chatgpt-bridge-status"
            className={cn(
              "rounded-full px-2 py-0.5 text-xs font-medium",
              status === "ready"
                ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                : status === "starting"
                  ? "bg-secondary text-muted-foreground"
                  : needsLogin
                    ? "bg-amber-500/15 text-amber-700 dark:text-amber-300"
                    : "bg-destructive/[0.12] text-destructive",
            )}
          >
            {t(`chatgpt_bridge.${status}`)}
          </span>
        )}
      </p>
      {needsLogin && <p className="leading-relaxed text-muted-foreground">{t("chatgpt_bridge.login_hint")}</p>}
      {error && <p className="text-destructive">{error}</p>}
      <div className="flex flex-wrap gap-2">
        {needsLogin && (
          <Button size="sm" disabled={busy} onClick={() => void run("login")}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <LogIn className="h-3.5 w-3.5" />}
            {t("chatgpt_bridge.login")}
          </Button>
        )}
        {status === "ready" && (
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void run("login")}>
            <LogIn className="h-3.5 w-3.5" />
            {t("chatgpt_bridge.relogin")}
          </Button>
        )}
        {(status === "offline" || status === "failed") && (
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void run("restart")}>
            <RotateCw className="h-3.5 w-3.5" />
            {t("chatgpt_bridge.restart")}
          </Button>
        )}
      </div>
    </div>
  );
}
