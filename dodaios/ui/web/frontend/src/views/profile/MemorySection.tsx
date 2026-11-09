/**
 * Memory and privacy — where the rest of what the assistant knows lives, and
 * what it will never keep.
 *
 * Five rows, each pointing at a real source:
 *   - your standing rules ({name}.md), edited in their own section;
 *   - the personal memory vault: how much it holds, one click away;
 *   - the profile file itself, USER.md, which opens in place;
 *   - the `## Do Not Record` categories, quoted from that file rather than
 *     restated in code, so the page can never promise more than the file says.
 */
import { ChevronRight, FileText, NotebookPen, ScrollText, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { useAgentInstructions } from "@/hooks/useAgentInstructions";
import { fill, useI18nStore, useLocaleChunk, useT } from "@/i18n";
import { localeForUiLanguage } from "@/components/runs/format";
import { useEventStore } from "@/store/events";
import { ProfileGroup, SettingRow } from "@/views/profile/ProfileGroup";
import { useVaultOverview } from "@/lib/personalMemoryApi";
import { parseDoNotRecord, shortenCategory } from "@/views/profile/provenance";


function RowLabel({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <span className="flex items-center gap-2.5">
      <span aria-hidden className="text-muted-foreground [&>svg]:h-4 [&>svg]:w-4">
        {icon}
      </span>
      {children}
    </span>
  );
}

/** Hints line up under the label text, past the icon. */
const HINT_INDENT = "pl-[1.625rem]";

export function MemorySection({
  raw,
  fileUpdatedMs,
  onOpenSource,
  bare = false,
}: {
  /** Kept for callers; the memory row no longer needs the name. */
  name?: string | null;
  raw: string | null;
  fileUpdatedMs: number | null;
  onOpenSource: () => void;
  /** Rendered inside a panel that already carries the section's title. */
  bare?: boolean;
}) {
  const t = useT();
  const setActiveSection = useEventStore((s) => s.setActiveSection);
  const rules = useAgentInstructions();
  useLocaleChunk("memory");
  const vault = useVaultOverview();
  const categories = parseDoNotRecord(raw);


  const rulesContent = rules.config?.content?.trim() ?? "";
  const hasRules = !!rules.config?.exists && rulesContent.length > 0;
  const ruleLines = hasRules ? rulesContent.split("\n").filter((l) => l.trim()).length : 0;
  const rulesFile = rules.config?.filename ?? "";


  const fileDate = fileUpdatedMs
    ? new Date(fileUpdatedMs).toLocaleDateString(localeForUiLanguage(useI18nStore.getState().ui), {
        day: "numeric",
        month: "short",
        year: "numeric",
      })
    : null;

  return (
    <ProfileGroup
      testId="memory"
      title={t("profile_view.memory_title")}
      description={t("profile_view.memory_description")}
      bare={bare}
    >
      <SettingRow
        testId="rules-row"
        label={<RowLabel icon={<ScrollText />}>{t("profile_view.rules_title")}</RowLabel>}
        hint={
          <span className={HINT_INDENT}>
            {rules.loading
              ? "…"
              : hasRules
                ? t("profile_view.rules_open").replace("{0}", String(ruleLines)).replace("{1}", rulesFile)
                : t("profile_view.rules_empty_body")}
          </span>
        }
        control={
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setActiveSection("agent-instructions")}
          >
            {hasRules ? t("profile_view.open") : t("profile_view.rules_write")}
          </Button>
        }
      />


      <SettingRow
        testId="vault-row"
        label={<RowLabel icon={<NotebookPen />}>{t("vault.title")}</RowLabel>}
        hint={
          <span className={HINT_INDENT}>
            {vault.data ? fill(t("vault.count"), { count: vault.data.stats.current }) : "…"}
          </span>
        }
        control={
          <Button type="button" size="sm" variant="outline" onClick={() => setActiveSection("memory")}>
            {t("profile_view.open")}
          </Button>
        }
      />

      <SettingRow
        testId="source-row"
        label={<RowLabel icon={<FileText />}>{t("profile_view.file_title")}</RowLabel>}
        hint={
          <span className={HINT_INDENT}>
            {fileDate
              ? t("profile_view.file_hint_dated").replace("{0}", fileDate)
              : t("profile_view.file_hint")}
          </span>
        }
        control={
          <Button type="button" size="sm" variant="outline" onClick={onOpenSource}>
            {t("profile_view.file_open")}
            <ChevronRight aria-hidden />
          </Button>
        }
      />

      {categories.length > 0 && (
        <SettingRow
          label={<RowLabel icon={<ShieldCheck />}>{t("profile_view.never_title")}</RowLabel>}
          hint={<span className={HINT_INDENT}>{t("profile_view.never_body")}</span>}
        >
          <ul data-testid="never-stored" className={`mt-3 flex flex-wrap gap-1.5 ${HINT_INDENT}`}>
            {categories.map((c) => (
              <li
                key={c}
                title={c}
                className="rounded-md border border-border bg-secondary px-2 py-0.5 text-sm text-foreground"
              >
                {shortenCategory(c)}
              </li>
            ))}
          </ul>
        </SettingRow>
      )}
    </ProfileGroup>
  );
}
