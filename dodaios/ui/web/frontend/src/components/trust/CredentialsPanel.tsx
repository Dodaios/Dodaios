import { useCallback, useEffect, useState } from "react";
import { KeyRound, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { fill, useT } from "@/i18n";
import {
  fetchCredentials,
  revokeCredentialRule,
  setCredentialBackend,
  setCredentialOtpMail,
  setCredentialSession,
  type CredentialsOverview,
} from "@/lib/trustApi";
import { useEventStore } from "@/store/events";

/**
 * Settings → Trust → Credentials. Shows the handles an agent may name (never a
 * value), where they come from (the app's own vault, Bitwarden or 1Password)
 * and whether that source is unlocked, the sites an agent may sign in to
 * without asking, and a revoke for each. The owner unlocks a manager
 * themselves; the only thing typed here is the manager's own session key, and
 * the master password is never asked for.
 */
export function CredentialsPanel() {
  const t = useT();
  const pushToast = useEventStore((s) => s.pushToast);
  const [data, setData] = useState<CredentialsOverview | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sessionKey, setSessionKey] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await fetchCredentials());
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const act = async (run: () => Promise<unknown>, doneKey: string, failKey: string) => {
    if (busy) return;
    setBusy(true);
    try {
      await run();
      pushToast("success", t(doneKey));
      await load();
    } catch {
      pushToast("error", t(failKey));
    } finally {
      setBusy(false);
    }
  };

  if (failed) return <p className="py-6 text-sm text-destructive">{t("trust.page.cred_load_failed")}</p>;
  if (!data) {
    return (
      <p className="flex items-center gap-2 py-6 text-sm text-muted-foreground" data-testid="credentials-loading">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("trust.page.loading")}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-10 pt-6" data-testid="credentials-panel">
      <section>
        <h2 className="m-0 flex items-center gap-2 text-base font-semibold text-foreground">
          <KeyRound aria-hidden className="h-4 w-4" />
          {t("trust.page.cred_title")}
        </h2>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{t("trust.page.cred_intro")}</p>
      </section>

      <section>
        <h2 className="m-0 text-base font-semibold text-foreground">{t("trust.page.cred_backend_title")}</h2>
        <ul className="mt-4 divide-y divide-border rounded-lg border border-border" data-testid="credentials-backends">
          {data.backends.map((b) => {
            const active = data.backend === b.name;
            return (
              <li key={b.name} className="flex flex-col gap-2 px-4 py-3" data-testid="credentials-backend">
                <div className="flex items-center gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="m-0 text-sm text-foreground">{t(`trust.page.cred_backend_${b.name}`)}</p>
                    <p className="m-0 text-xs text-muted-foreground" data-testid="credentials-backend-state">
                      {t(`trust.page.cred_state_${b.state}`)}
                    </p>
                  </div>
                  {active ? (
                    <span className="text-xs text-foreground-secondary">{t("trust.page.cred_in_use")}</span>
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy || !b.installed}
                      data-testid="credentials-backend-use"
                      onClick={() => void act(() => setCredentialBackend(b.name), "trust.page.cred_saved", "trust.page.cred_save_failed")}
                    >
                      {t("trust.page.cred_use_backend")}
                    </Button>
                  )}
                </div>
                {b.name === "1password" && b.installed && !b.unlocked && (
                  <p className="m-0 text-xs text-muted-foreground">{t("trust.page.cred_hint_1password")}</p>
                )}
                {b.name === "bitwarden" && b.installed && (
                  <div className="flex flex-col gap-2">
                    {!b.unlocked && <p className="m-0 text-xs text-muted-foreground">{t("trust.page.cred_hint_bitwarden")}</p>}
                    <div className="flex items-center gap-2">
                      <Input
                        type="password"
                        value={sessionKey}
                        onChange={(e) => setSessionKey(e.target.value)}
                        placeholder={t("trust.page.cred_session_label")}
                        aria-label={t("trust.page.cred_session_label")}
                        autoComplete="off"
                        data-1p-ignore
                        data-lpignore="true"
                        maxLength={512}
                        data-testid="credentials-session-key"
                      />
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busy || sessionKey.trim() === ""}
                        data-testid="credentials-session-use"
                        onClick={() =>
                          void act(async () => {
                            await setCredentialSession(b.name, sessionKey.trim());
                            setSessionKey("");
                          }, "trust.page.cred_session_saved", "trust.page.cred_session_failed")
                        }
                      >
                        {t("trust.page.cred_session_use")}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        data-testid="credentials-session-lock"
                        onClick={() => void act(() => setCredentialSession(b.name, ""), "trust.page.cred_session_cleared", "trust.page.cred_session_failed")}
                      >
                        {t("trust.page.cred_session_lock")}
                      </Button>
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </section>

      <section>
        <h2 className="m-0 text-base font-semibold text-foreground">{t("trust.page.cred_handles_title")}</h2>
        {data.handles.length === 0 ? (
          <p className="mt-4 text-sm text-foreground-secondary" data-testid="credentials-handles-empty">
            {t("trust.page.cred_handles_empty")}
          </p>
        ) : (
          <ul className="mt-4 divide-y divide-border rounded-lg border border-border" data-testid="credentials-handles">
            {data.handles.map((h) => (
              <li key={`${h.agent_id}:${h.handle}`} className="flex items-center gap-3 px-4 py-2.5" data-testid="credentials-handle">
                <code className="min-w-0 flex-1 truncate text-sm text-foreground">{h.handle}</code>
                {h.agent && <span className="text-xs text-muted-foreground">{h.agent}</span>}
                {h.has_totp && <span className="text-xs text-foreground-secondary">{t("trust.page.cred_totp")}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="m-0 text-base font-semibold text-foreground">{t("trust.page.cred_rules_title")}</h2>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{t("trust.page.cred_rules_intro")}</p>
        {data.rules.length === 0 ? (
          <p className="mt-4 text-sm text-foreground-secondary" data-testid="credentials-rules-empty">
            {t("trust.page.cred_rules_empty")}
          </p>
        ) : (
          <ul className="mt-4 divide-y divide-border rounded-lg border border-border" data-testid="credentials-rules">
            {data.rules.map((rule) => (
              <li key={rule.id} className="flex items-center gap-3 px-4 py-3" data-testid="credentials-rule">
                <p className="m-0 min-w-0 flex-1 truncate text-sm text-foreground">
                  {fill(t("trust.page.cred_rule_row"), { agent: rule.agent, site: rule.domain })}
                </p>
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  {t("trust.page.cred_otp_mail")}
                  <Switch
                    checked={rule.otp_from_mail}
                    disabled={busy}
                    data-testid="credentials-rule-otp"
                    onCheckedChange={(on) => void act(() => setCredentialOtpMail(rule.id, on), "trust.page.cred_saved", "trust.page.cred_save_failed")}
                  />
                </label>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy}
                  data-testid="credentials-rule-revoke"
                  onClick={() => void act(() => revokeCredentialRule(rule.id), "trust.page.revoked", "trust.page.revoke_failed")}
                >
                  {t("trust.page.revoke")}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
