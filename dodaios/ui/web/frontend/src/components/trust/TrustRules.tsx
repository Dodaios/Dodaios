import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { fill, useT } from "@/i18n";
import {
  fetchKnownRecipients,
  fetchTrustRules,
  forgetRecipient,
  revokeAgentRule,
  revokeTrustRule,
  type AgentRule,
  type KnownRecipient,
  type TrustRule,
  type TrustRules as TrustRulesPayload,
} from "@/lib/trustApi";
import { useEventStore } from "@/store/events";

/** The rule as one sentence: "every Bash call", "Gmail: send", "Edit inside src". */
export function ruleSentence(rule: TrustRule, t: (key: string) => string): string {
  const tool = rule.app || rule.tool;
  const target = rule.label && rule.label !== rule.target ? rule.label : rule.target;
  return fill(t(`trust.page.kind_${rule.kind}`), { tool, target });
}

export function TrustRules() {
  const t = useT();
  const pushToast = useEventStore((s) => s.pushToast);
  const [data, setData] = useState<TrustRulesPayload | null>(null);
  const [recipients, setRecipients] = useState<KnownRecipient[]>([]);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [rules, known] = await Promise.all([fetchTrustRules(), fetchKnownRecipients().catch(() => [])]);
      setData(rules);
      setRecipients(known);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const act = async (key: string, run: () => Promise<unknown>, doneKey: string, failKey: string) => {
    if (busy) return;
    setBusy(key);
    try {
      await run();
      pushToast("success", t(doneKey));
      await load();
    } catch {
      pushToast("error", t(failKey));
    } finally {
      setBusy(null);
    }
  };

  if (failed) return <p className="py-6 text-sm text-destructive">{t("trust.page.load_failed")}</p>;
  if (!data) {
    return (
      <p className="flex items-center gap-2 py-6 text-sm text-muted-foreground" data-testid="trust-rules-loading">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("trust.page.loading")}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-10 pt-6" data-testid="trust-rules">
      <section>
        <h2 className="m-0 text-base font-semibold text-foreground">{t("trust.page.rules_title")}</h2>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{t("trust.page.rules_intro")}</p>
        {data.rules.length === 0 ? (
          <p className="mt-4 text-sm text-foreground-secondary" data-testid="trust-rules-empty">{t("trust.page.rules_empty")}</p>
        ) : (
          <ul className="mt-4 divide-y divide-border rounded-lg border border-border" data-testid="trust-rule-list">
            {data.rules.map((rule) => (
              <li key={rule.id} className="flex items-center gap-3 px-4 py-3" data-testid="trust-rule">
                <div className="min-w-0 flex-1">
                  <p className="m-0 truncate text-sm text-foreground" title={rule.target || rule.tool}>{ruleSentence(rule, t)}</p>
                  <p className="m-0 text-xs text-muted-foreground">{new Date(rule.created_ms).toLocaleDateString()}</p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy !== null}
                  data-testid="trust-rule-revoke"
                  onClick={() => void act(rule.id, () => revokeTrustRule(rule.id), "trust.page.revoked", "trust.page.revoke_failed")}
                >
                  {t("trust.page.revoke")}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {data.agent_rules.length > 0 && (
        <section>
          <h2 className="m-0 text-base font-semibold text-foreground">{t("trust.page.agent_rules_title")}</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{t("trust.page.agent_rules_intro")}</p>
          <ul className="mt-4 divide-y divide-border rounded-lg border border-border" data-testid="trust-agent-rule-list">
            {data.agent_rules.map((rule: AgentRule) => (
              <li key={`${rule.agent_id}:${rule.pattern}`} className="flex items-center gap-3 px-4 py-3" data-testid="trust-agent-rule">
                <p className="m-0 min-w-0 flex-1 truncate text-sm text-foreground">
                  {fill(t("trust.page.agent_rule_row"), { agent: rule.agent, rule: rule.label })}
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy !== null}
                  data-testid="trust-agent-rule-revoke"
                  onClick={() => void act(`${rule.agent_id}:${rule.pattern}`, () => revokeAgentRule(rule.agent_id, rule.pattern), "trust.page.revoked", "trust.page.revoke_failed")}
                >
                  {t("trust.page.revoke")}
                </Button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h2 className="m-0 text-base font-semibold text-foreground">{t("trust.page.limits_title")}</h2>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{t("trust.page.limits_intro")}</p>
        <ul className="mt-4 flex flex-col gap-2 text-sm text-foreground" data-testid="trust-hard-limits">
          {data.hard_limits.map((code) => (
            <li key={code} className="flex items-start gap-2">
              <span aria-hidden className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
              {t(`trust.page.limit_${code}`)}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="m-0 text-base font-semibold text-foreground">{t("trust.page.recipients_title")}</h2>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{t("trust.page.recipients_intro")}</p>
        {recipients.length === 0 ? (
          <p className="mt-4 text-sm text-foreground-secondary">{t("trust.page.recipients_empty")}</p>
        ) : (
          <ul className="mt-4 divide-y divide-border rounded-lg border border-border" data-testid="trust-recipients">
            {recipients.map((row) => (
              <li key={row.recipient} className="flex items-center gap-3 px-4 py-2.5">
                <span className="min-w-0 flex-1 truncate text-sm text-foreground">{row.recipient}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy !== null}
                  onClick={() => void act(row.recipient, () => forgetRecipient(row.recipient), "trust.page.revoked", "trust.page.revoke_failed")}
                >
                  {t("trust.page.forget")}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
