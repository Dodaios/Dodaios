/**
 * What reaches the model, drawn.
 *
 *   your memory (all of it)  ──▶  always in mind (a small, fixed block)  ──▶  every conversation
 *            └──────────── looked up when a question needs it ─────────────────┘
 *
 * plus the way back: after a conversation one background pass compares what
 * was said with what is stored and adds, updates or ends memories.
 */
import { ArrowRight, Brain, Compass, MessagesSquare, RefreshCcw, Search } from "lucide-react";
import { fill, useT } from "@/i18n";
import type { VaultOverview } from "@/lib/personalMemoryApi";

export function HowItWorks({
  name,
  overview,
  onShowInMind,
}: {
  name: string;
  overview: VaultOverview;
  onShowInMind: () => void;
}) {
  const t = useT();
  const used = overview.used_chars;
  const budget = Math.max(1, overview.budget_chars);
  const share = Math.min(1, used / budget);
  const tokens = Math.round(used / 4);
  const total = overview.stats.current;
  const inMind = overview.in_mind_ids.length;

  return (
    <div data-testid="vault-how" className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[880px] px-6 py-10">
        <p className="text-center text-[13px] text-muted-foreground">{t("vault.how_kicker")}</p>
        <h2 className="mt-1 text-center text-[26px] font-semibold tracking-tight text-foreground-strong">
          {fill(t("vault.how_title"), { name })}
        </h2>

        {/* The flow */}
        <div className="mt-10 grid grid-cols-1 items-center gap-4 md:grid-cols-[1fr_auto_1.15fr_auto_1fr]">
          <Node
            icon={<Brain className="h-5 w-5" />}
            tone="220 9% 56%"
            title={t("vault.how_store")}
            big={String(total)}
            caption={t("vault.how_store_caption")}
          />
          <Arrow />
          <button
            type="button"
            onClick={onShowInMind}
            className="rounded-2xl border border-accent/40 bg-accent/[0.07] p-5 text-left transition-colors hover:bg-accent/[0.1] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <div className="flex items-center gap-2 text-accent">
              <Compass className="h-5 w-5" />
              <span className="text-[13px] font-semibold">{t("vault.shelf_in_mind")}</span>
            </div>
            <p className="mt-3 text-[30px] font-semibold leading-none tabular-nums text-foreground-strong">{inMind}</p>
            <p className="mt-1 text-[12px] text-muted-foreground">{t("vault.how_in_mind_caption")}</p>
            <div
              className="mt-4 h-2 overflow-hidden rounded-full bg-sheen/[0.08]"
              role="meter"
              aria-valuemin={0}
              aria-valuemax={budget}
              aria-valuenow={used}
              aria-label={t("vault.how_budget")}
            >
              <div className="h-full rounded-full bg-accent motion-safe:transition-[width]" style={{ width: `${share * 100}%` }} />
            </div>
            <p className="mt-1.5 text-[11px] tabular-nums text-muted-foreground">
              {fill(t("vault.how_budget_line"), { used, budget, tokens })}
            </p>
          </button>
          <Arrow />
          <Node
            icon={<MessagesSquare className="h-5 w-5" />}
            tone="142 58% 46%"
            title={t("vault.how_conversation")}
            big="∞"
            caption={fill(t("vault.how_conversation_caption"), { name })}
          />
        </div>

        {/* The lookup path */}
        <div className="relative mx-auto mt-4 hidden h-10 md:block" aria-hidden>
          <svg className="absolute inset-0 h-full w-full" preserveAspectRatio="none" viewBox="0 0 100 40">
            <path d="M14 0 V24 Q14 32 22 32 H78 Q86 32 86 24 V0" fill="none" stroke="hsl(var(--border-strong))" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />
          </svg>
        </div>
        <div className="mx-auto mt-1 flex max-w-[520px] items-start gap-3 rounded-xl border border-dashed border-border-strong bg-sheen/[0.02] p-4">
          <Search className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <div>
            <p className="text-[13px] font-medium text-foreground">{t("vault.how_lookup")}</p>
            <p className="mt-0.5 text-[12px] leading-relaxed text-muted-foreground">{fill(t("vault.how_lookup_body"), { name })}</p>
          </div>
        </div>

        {/* The way back */}
        <div className="mt-12 grid gap-3 md:grid-cols-3">
          <Step n={1} title={t("vault.how_learn_1")} body={t("vault.how_learn_1_body")} />
          <Step n={2} title={t("vault.how_learn_2")} body={t("vault.how_learn_2_body")} />
          <Step n={3} title={t("vault.how_learn_3")} body={t("vault.how_learn_3_body")} />
        </div>
        <p className="mt-6 flex items-center justify-center gap-2 text-center text-[12px] text-muted-foreground">
          <RefreshCcw className="h-3.5 w-3.5" /> {t("vault.how_footer")}
        </p>
      </div>
    </div>
  );
}

function Node({
  icon,
  tone,
  title,
  big,
  caption,
}: {
  icon: React.ReactNode;
  tone: string;
  title: string;
  big: string;
  caption: string;
}) {
  return (
    <div className="rounded-2xl border border-border bg-sheen/[0.02] p-5">
      <div className="flex items-center gap-2" style={{ color: `hsl(${tone})` }}>
        {icon}
        <span className="text-[13px] font-semibold text-foreground">{title}</span>
      </div>
      <p className="mt-3 text-[30px] font-semibold leading-none tabular-nums text-foreground-strong">{big}</p>
      <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">{caption}</p>
    </div>
  );
}

function Arrow() {
  return (
    <div className="flex justify-center text-faint-foreground" aria-hidden>
      <ArrowRight className="h-5 w-5 rotate-90 md:rotate-0" />
    </div>
  );
}

function Step({ n, title, body }: { n: number; title: string; body: string }) {
  return (
    <div className="rounded-2xl border border-border p-4">
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-sheen/[0.08] text-[12px] font-semibold text-foreground">
        {n}
      </span>
      <p className="mt-3 text-[13px] font-medium text-foreground">{title}</p>
      <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">{body}</p>
    </div>
  );
}
