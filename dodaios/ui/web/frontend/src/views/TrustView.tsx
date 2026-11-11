/**
 * Settings → Trust and privacy. Two calm pages behind one tab bar:
 *
 * - "Without asking": what the assistant may do without a card (the standing
 *   rules from approval cards, each with Revoke), the agents' own rules, the
 *   hard limits no rule lifts, and who has been written to from here.
 * - "What it knows": connected accounts, what is learned (with the learning
 *   switch), which providers see what (local vs cloud), channels, the screen.
 *
 * - "Credentials": the logins agents may name by handle (never a value), the
 *   backend they come from and its lock state, and the sites allowed to sign in.
 * - "Self-changes": what the assistant changed in itself (skills, instructions, tools,
 *   code), each with its diff and regression result, one-click rollback, and the
 *   owner approval that core changes wait for.
 * - "Activity log": every tool action with who started it, how it was approved,
 *   how it ended and its receipt; read-only, exportable as CSV or JSON.
 *
 * Strings live in the `trust` locale chunk; the view waits for it so no key
 * ever paints.
 */
import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { TabBar } from "@/components/layout/SectionTabBar";
import { AuditLog } from "@/components/trust/AuditLog";
import { CredentialsPanel } from "@/components/trust/CredentialsPanel";
import { PrivacyOverview } from "@/components/trust/PrivacyOverview";
import { SelfChanges } from "@/components/trust/SelfChanges";
import { TrustRules } from "@/components/trust/TrustRules";
import { useLocaleChunk, useT } from "@/i18n";

type Tab = "rules" | "privacy" | "credentials" | "changes" | "audit";

export function TrustView({ initialTab = "rules" }: { initialTab?: Tab }) {
  const ready = useLocaleChunk("trust");
  const t = useT();
  const [tab, setTab] = useState<Tab>(initialTab);
  if (!ready) return <div className="px-6 py-8 text-sm text-muted-foreground" data-testid="trust-loading" />;
  return (
    <div className="flex h-full min-h-0 flex-col px-6" data-testid="trust-view">
      <PageHeader
        icon={<ShieldCheck />}
        title={t("trust.page.title")}
        description={t("trust.page.description")}
        tabs={
          <TabBar
            tabs={[
              { id: "rules", label: t("trust.page.tab_rules") },
              { id: "privacy", label: t("trust.page.tab_privacy") },
              { id: "credentials", label: t("trust.page.tab_credentials") },
              { id: "changes", label: t("trust.page.tab_changes") },
              { id: "audit", label: t("trust.page.tab_audit") },
            ]}
            active={tab}
            onChange={(id) => setTab(id as Tab)}
          />
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto pb-10 scrollbar-jarvis">
        {tab === "rules" ? (
          <TrustRules />
        ) : tab === "privacy" ? (
          <PrivacyOverview />
        ) : tab === "credentials" ? (
          <CredentialsPanel />
        ) : tab === "changes" ? (
          <SelfChanges />
        ) : (
          <AuditLog />
        )}
      </div>
    </div>
  );
}
