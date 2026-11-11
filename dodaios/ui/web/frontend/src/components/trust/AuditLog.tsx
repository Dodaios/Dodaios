import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { fill, useT } from "@/i18n";
import { openExternalUrl } from "@/lib/openExternal";
import { auditExportUrl, fetchAudit, type AuditEntry, type AuditFilter, type AuditPage } from "@/lib/trustApi";

const ORIGINS = ["owner", "routine", "trigger", "agent"] as const;

function ReceiptCell({ entry }: { entry: AuditEntry }) {
  const t = useT();
  const receipt = entry.receipt;
  if (!receipt) return <span className="text-muted-foreground">-</span>;
  if (receipt.state === "none") return <span className="text-muted-foreground">{t("trust.page.audit_receipt_none")}</span>;
  const link = receipt.links.find((l) => /^https?:\/\//.test(l));
  return (
    <span className="[overflow-wrap:anywhere]">
      {receipt.summary}
      {link ? (
        <>
          {" "}
          <a
            href={link}
            className="text-primary underline"
            onClick={(event) => {
              event.preventDefault();
              void openExternalUrl(link);
            }}
          >
            {t("work_trace.receipt")}
          </a>
        </>
      ) : null}
    </span>
  );
}

function Select({ label, value, options, onChange }: {
  label: string; value: string; options: { value: string; label: string }[]; onChange: (next: string) => void;
}) {
  const t = useT();
  return (
    <label className="flex flex-col gap-1 text-xs text-muted-foreground">
      {label}
      <select
        className="h-8 rounded-md border border-border bg-background px-2 text-sm text-foreground"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{t("trust.page.audit_filter_all")}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </label>
  );
}

/** Settings, Trust and privacy, Activity log. Read-only: there is nothing to edit or delete. */
export function AuditLog() {
  const t = useT();
  const [filter, setFilter] = useState<AuditFilter>({});
  const [page, setPage] = useState<AuditPage | null>(null);
  const [rows, setRows] = useState<AuditEntry[]>([]);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async (next: AuditFilter, append: boolean) => {
    try {
      const data = await fetchAudit(next);
      setPage(data);
      setRows((prev) => (append ? [...prev, ...data.entries] : data.entries));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);
  useEffect(() => {
    void load(filter, false);
  }, [filter, load]);

  const set = (patch: AuditFilter) => setFilter((f) => ({ ...f, ...patch, before: undefined }));

  if (failed) return <p className="py-6 text-sm text-muted-foreground" role="alert">{t("trust.page.audit_load_failed")}</p>;
  if (!page) return <p className="py-6 text-sm text-muted-foreground">…</p>;
  return (
    <section data-testid="trust-audit" className="max-w-5xl">
      <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{t("trust.page.audit_intro")}</p>
      <p
        className={page.chain.ok ? "mt-2 text-xs text-muted-foreground" : "mt-2 text-xs text-destructive"}
        data-testid="audit-chain"
      >
        {page.chain.ok
          ? fill(t("trust.page.audit_chain_ok"), { count: String(page.chain.rows) })
          : fill(t("trust.page.audit_chain_broken"), { seq: String(page.chain.broken_at ?? "") })}
      </p>
      <div className="mt-4 flex flex-wrap items-end gap-3">
        <Select
          label={t("trust.page.audit_filter_day")}
          value={filter.day ?? ""}
          options={page.days.map((d) => ({ value: d, label: d }))}
          onChange={(day) => set({ day })}
        />
        <Select
          label={t("trust.page.audit_filter_tool")}
          value={filter.tool ?? ""}
          options={page.tools.map((d) => ({ value: d, label: d }))}
          onChange={(tool) => set({ tool })}
        />
        <Select
          label={t("trust.page.audit_filter_origin")}
          value={filter.origin ?? ""}
          options={ORIGINS.map((o) => ({ value: o, label: t(`trust.page.audit_origin_${o}`) }))}
          onChange={(origin) => set({ origin })}
        />
        <div className="ml-auto flex gap-2">
          <Button asChild variant="outline" size="sm">
            <a href={auditExportUrl("csv", filter)} download>{t("trust.page.audit_export_csv")}</a>
          </Button>
          <Button asChild variant="outline" size="sm">
            <a href={auditExportUrl("json", filter)} download>{t("trust.page.audit_export_json")}</a>
          </Button>
        </div>
      </div>
      {rows.length === 0 ? (
        <p className="mt-6 text-sm text-muted-foreground">{t("trust.page.audit_empty")}</p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr>
                {["time", "tool", "origin", "approval", "outcome", "receipt"].map((c) => (
                  <th key={c} className="py-2 pr-4 font-medium">{t(`trust.page.audit_col_${c}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-t border-border align-top" data-testid="audit-row">
                  <td className="whitespace-nowrap py-2 pr-4 tabular-nums">{new Date(row.ts_ms).toLocaleString()}</td>
                  <td className="py-2 pr-4">
                    {row.tool}
                    {row.action ? <span className="text-muted-foreground"> · {row.action}</span> : null}
                  </td>
                  <td className="py-2 pr-4">
                    {t(`trust.page.audit_origin_${row.origin}`)}
                    {row.origin_detail ? (
                      <span className="block text-xs text-muted-foreground [overflow-wrap:anywhere]">{row.origin_detail}</span>
                    ) : null}
                  </td>
                  <td className="py-2 pr-4">{t(`trust.page.audit_approval_${row.approval}`)}</td>
                  <td className="py-2 pr-4">
                    {t(`trust.page.audit_outcome_${row.outcome}`)}
                    {row.error ? (
                      <span className="block text-xs text-muted-foreground [overflow-wrap:anywhere]">{row.error.slice(0, 160)}</span>
                    ) : null}
                  </td>
                  <td className="py-2"><ReceiptCell entry={row} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {page.next_before ? (
        <Button className="mt-4" variant="outline" size="sm" onClick={() => void load({ ...filter, before: page.next_before ?? undefined }, true)}>
          {t("trust.page.audit_older")}
        </Button>
      ) : null}
    </section>
  );
}
