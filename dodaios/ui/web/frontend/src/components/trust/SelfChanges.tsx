import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { fill, useT } from "@/i18n";
import {
  decideSelfChange,
  fetchSelfChanges,
  rollbackSelfChangesSince,
  type SelfChange,
  type SelfChangeSummary,
} from "@/lib/trustApi";
import { useEventStore } from "@/store/events";

const HOUR = 3_600_000;
const WINDOWS = [
  { id: "hour", ms: HOUR },
  { id: "day", ms: 24 * HOUR },
  { id: "week", ms: 7 * 24 * HOUR },
] as const;

type Action = "approve" | "reject" | "keep" | "rollback";

/** Settings, Trust and privacy, Self-changes: what the assistant changed in itself, with one-click undo. */
export function SelfChanges() {
  const t = useT();
  const pushToast = useEventStore((s) => s.pushToast);
  const [rows, setRows] = useState<SelfChange[] | null>(null);
  const [summary, setSummary] = useState<SelfChangeSummary | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [armed, setArmed] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await fetchSelfChanges();
      setRows(data.changes);
      setSummary(data.summary);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const act = async (key: string, run: () => Promise<{ reverted?: SelfChange[] }>, bulk = false) => {
    if (busy) return;
    setBusy(key);
    try {
      const result = await run();
      pushToast(
        "success",
        bulk ? fill(t("trust.page.changes_reverted_n"), { count: result.reverted?.length ?? 0 }) : t("trust.page.change_done"),
      );
      await load();
    } catch {
      pushToast("error", t("trust.page.change_failed"));
    } finally {
      setBusy(null);
      setArmed(null);
    }
  };

  if (failed) return <p className="py-6 text-sm text-destructive">{t("trust.page.load_failed")}</p>;
  if (!rows || !summary) {
    return (
      <p className="flex items-center gap-2 py-6 text-sm text-muted-foreground" data-testid="self-changes-loading">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("trust.page.loading")}
      </p>
    );
  }

  const decide = (row: SelfChange, action: Action) => (
    <Button
      variant={action === "approve" ? "default" : "outline"}
      size="sm"
      disabled={busy !== null}
      data-testid={`self-change-${action}`}
      onClick={() => void act(row.id, () => decideSelfChange(row.id, action))}
    >
      {t(`trust.page.change_${action === "reject" ? "refuse" : action}`)}
    </Button>
  );

  return (
    <div className="flex flex-col gap-6 pt-6" data-testid="self-changes">
      <section>
        <h2 className="m-0 text-base font-semibold text-foreground">{t("trust.page.changes_title")}</h2>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{t("trust.page.changes_intro")}</p>
        {rows.length > 0 && (
          <>
            <p className="mt-3 text-xs text-muted-foreground" data-testid="self-changes-counts">
              {fill(t("trust.page.changes_counts"), {
                waiting: summary.waiting,
                trial: summary.on_trial,
                live: summary.live,
                reverted: summary.reverted,
                blocked: summary.blocked,
              })}
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-foreground-secondary">
              <span>{t("trust.page.changes_revert_label")}</span>
              {WINDOWS.map((w) =>
                armed === w.ms ? (
                  <Button
                    key={w.id}
                    variant="destructive"
                    size="sm"
                    disabled={busy !== null}
                    data-testid="self-changes-revert-confirm"
                    onClick={() => void act(`since-${w.id}`, () => rollbackSelfChangesSince(Date.now() - w.ms), true)}
                  >
                    {t("trust.page.changes_revert_confirm")}
                  </Button>
                ) : (
                  <Button
                    key={w.id}
                    variant="outline"
                    size="sm"
                    disabled={busy !== null}
                    data-testid={`self-changes-since-${w.id}`}
                    onClick={() => setArmed(w.ms)}
                  >
                    {t(`trust.page.changes_since_${w.id}`)}
                  </Button>
                ),
              )}
            </div>
          </>
        )}
        {rows.length === 0 ? (
          <p className="mt-4 text-sm text-foreground-secondary" data-testid="self-changes-empty">
            {t("trust.page.changes_empty")}
          </p>
        ) : (
          <ul className="mt-4 divide-y divide-border rounded-lg border border-border" data-testid="self-change-list">
            {rows.map((row) => {
              const active = row.state === "trial" || row.state === "live";
              const why = row.core_reasons.join("; ") || row.note;
              const checks = row.gate.checks ?? [];
              return (
                <li key={row.id} className="flex flex-col gap-2 px-4 py-3" data-testid="self-change">
                  <div className="flex items-start gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="m-0 text-sm text-foreground [overflow-wrap:anywhere]">
                        <span className="text-muted-foreground">{t(`trust.page.surface_${row.surface}`)}</span> {row.target}
                      </p>
                      {row.reason && (
                        <p className="m-0 text-xs text-foreground-secondary [overflow-wrap:anywhere]">{row.reason}</p>
                      )}
                      <p className="m-0 text-xs text-muted-foreground">
                        {fill(t("trust.page.change_by"), { author: row.author, version: row.version })} ·{" "}
                        {new Date(row.created_ms).toLocaleString()}
                      </p>
                      {row.state === "proposed" && (
                        <p className="m-0 text-xs text-foreground-secondary">
                          {fill(t("trust.page.change_needs_owner"), { why })}
                        </p>
                      )}
                      {row.state === "blocked" && row.note && (
                        <p className="m-0 text-xs text-destructive">{fill(t("trust.page.change_blocked"), { why: row.note })}</p>
                      )}
                    </div>
                    <span
                      className="shrink-0 rounded-full border border-border px-2 py-0.5 text-xs text-foreground-secondary"
                      data-testid="self-change-state"
                    >
                      {t(`trust.page.state_${row.state}`)}
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {row.state === "proposed" && (
                      <>
                        {decide(row, "approve")}
                        {decide(row, "reject")}
                      </>
                    )}
                    {row.state === "trial" && decide(row, "keep")}
                    {active && decide(row, "rollback")}
                    <Button
                      variant="ghost"
                      size="sm"
                      data-testid="self-change-diff-toggle"
                      onClick={() => setOpen(open === row.id ? null : row.id)}
                    >
                      {t(open === row.id ? "trust.page.change_hide_diff" : "trust.page.change_show_diff")}
                    </Button>
                  </div>
                  {open === row.id && (
                    <div className="flex flex-col gap-2" data-testid="self-change-detail">
                      {checks.length > 0 && (
                        <p className="m-0 text-xs text-foreground-secondary">
                          {fill(t("trust.page.change_checks"), {
                            summary: checks.map((c) => `${c.name} ${c.status}${c.detail ? ` (${c.detail})` : ""}`).join("; "),
                          })}
                        </p>
                      )}
                      {row.diff ? (
                        <pre className="m-0 max-h-72 overflow-auto rounded-md border border-border bg-sheen/[0.04] p-3 text-xs text-foreground scrollbar-jarvis">
                          {row.diff}
                        </pre>
                      ) : (
                        <p className="m-0 text-xs text-muted-foreground">{t("trust.page.change_no_diff")}</p>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
