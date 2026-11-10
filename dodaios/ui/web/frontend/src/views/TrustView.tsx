/**
 * Settings → Trust and privacy. Two calm pages behind one tab bar:
 *
 * - "Without asking": what the assistant may do without a card (the standing
 *   rules from approval cards, each with Revoke), the agents' own rules, the
 *   hard limits no rule lifts, and who has been written to from here.
 * - "What it knows": connected accounts, what is learned (with the learning
 *   switch), which providers see what (local vs cloud), channels, the screen.
 *
 * Strings live in the `trust` locale chunk; the view waits for it so no key
 * ever paints.
 */
import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { TabBar } from "@/components/layout/SectionTabBar";
import { PrivacyOverview } from "@/components/trust/PrivacyOverview";
import { TrustRules } from "@/components/trust/TrustRules";
import { useLocaleChunk, useT } from "@/i18n";

type Tab = "rules" | "privacy";

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
            ]}
            active={tab}
            onChange={(id) => setTab(id as Tab)}
          />
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto pb-10 scrollbar-jarvis">
        {tab === "rules" ? <TrustRules /> : <PrivacyOverview />}
      </div>
    </div>
  );
}
