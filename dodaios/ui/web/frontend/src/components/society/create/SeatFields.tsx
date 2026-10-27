/**
 * What a new agent runs on: its runtime (Jarvis, Hermes or OpenClaw — fixed
 * for the agent's life), the provider, how it pays (subscription, API key or
 * local), the login and the model. Only what is connected on this machine is
 * offered (`seatChoice.ts`). Every path of the New-agent dialog — blank, a
 * starter, an imported template — shares this one choice, so a starter works
 * on any runtime and any provider exactly like a blank agent.
 */
import { useEffect, useMemo, useState } from "react";
import { ChevronDown, Loader2, RefreshCw, TriangleAlert } from "lucide-react";
import { BrandedSelect } from "@/components/ui/select";
import { AgentMark } from "@/components/agentic/AgentMark";
import { ProviderLogo } from "@/components/providers/ProviderLogo";
import { useT } from "@/i18n";
import type { AgentRuntime } from "@/lib/societyApi";
import { useModelAccess, type ModelAccess } from "@/lib/modelAccess";
import { cn } from "@/lib/utils";
import { RuntimeChoice, useAgentRuntimes } from "../card/RuntimePicker";
import { SandboxChoice } from "../card/AgentSandboxSection";
import { modelSeats, runtimeSeats } from "../chat/modelChoices";
import { useModelMenuData } from "../chat/useModelMenuData";
import { accountChoice, accountHint } from "./brainPicker";
import { AccessChoice } from "./AccessChoice";
import { accessModels, billedPerUse, defaultModel, pickableOption, providerChoices, type AccessBlocked, type AccessOption, type ProviderChoice } from "./seatChoice";

/** A model list this long gets a search field. */
const SEARCH_FROM = 12;

function list(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

/** What the create request carries for the seat; blanks keep the backend defaults. */
export interface SeatPick {
  runtime: AgentRuntime;
  executionEnvironment: "local" | "sandbox";
  provider?: string;
  model?: string;
  accountId?: string;
}

export function useCreateSeat() {
  const t = useT();
  const runtimes = useAgentRuntimes();
  const [runtime, setRuntimeState] = useState<AgentRuntime>("jarvis");
  const [executionEnvironment, setExecutionEnvironment] = useState<"local" | "sandbox">("local");
  const [providerId, setProviderId] = useState("");
  const [access, rememberAccess] = useModelAccess();
  // The access picked in THIS dialog. A remembered one (from the chat's model
  // picker) never moves a fresh agent onto a seat billed per use.
  const [pickedAccess, setPickedAccess] = useState<Record<string, string>>({});
  const [model, setModel] = useState("");
  const [account, setAccount] = useState("");
  const [accountProvider, setAccountProvider] = useState("");
  // A stored catalog may be a startup fallback. Revalidate on this user gesture,
  // and scope subscription models to the login that will actually run the agent.
  const menu = useModelMenuData(null, undefined,
    account && accountProvider ? { [accountProvider]: account } : {}, { refreshOnMount: true });

  const external = runtime !== "jarvis";
  const defaultModelLabel = t("agent_chat.model_default");
  const data = runtimes.data;
  const supportedKey = list(data?.supported_providers).join(",");
  const gatewayKey = list(data?.subscription_providers).join(",");
  const loginKey = list(data?.login_providers).join(",");
  const accessKey = JSON.stringify(data?.access && typeof data.access === "object" ? data.access : {});
  // Refusals only concern Hermes / OpenClaw (Claude's login billed as Extra Usage).
  const blockedKey = JSON.stringify(external && data?.access_blocked && typeof data.access_blocked === "object" ? data.access_blocked : {});
  const choices = useMemo(() => {
    const all = modelSeats(menu.options, Array.isArray(menu.providers) ? menu.providers : [], menu.live, defaultModelLabel);
    const split = (key: string) => key.split(",").filter(Boolean);
    const seats = external ? runtimeSeats(all, split(supportedKey), split(gatewayKey), split(loginKey)) : all;
    return providerChoices(seats, JSON.parse(accessKey) as Record<string, string[]>, external, JSON.parse(blockedKey) as AccessBlocked);
  }, [menu.options, menu.providers, menu.live, defaultModelLabel, external, supportedKey, gatewayKey, loginKey, accessKey, blockedKey]);

  // The person's picks stay while they are offered; a pick that disappears (a
  // key removed, another runtime chosen) falls back to the first one left.
  const chosen = choices.find((choice) => choice.id === providerId)
    ?? choices.find((choice) => pickableOption(choice)) ?? choices[0] ?? null;
  // A refused access is listed with its reason but never picked.
  const option: AccessOption | null = chosen ? startingOption(chosen, pickedAccess[chosen.id], access[chosen.id]) : null;
  const models = accessModels(option);
  const accounts = accountChoice(option?.seat ?? null);
  const modelValue = models.some((entry) => entry.id === model) ? model : defaultModel(option);
  const accountValue = option?.seat.provider.id === accountProvider && accounts.some((entry) => entry.id === account) ? account : "";
  const seatKey = `${chosen?.id ?? ""}|${option?.kind ?? ""}|${accountValue}`;
  useEffect(() => {
    // Another provider or access: its own default model, not the last one's id.
    setModel("");
  }, [seatKey]);

  // A runtime still being set up does not hold creation back: the agent's
  // first turn waits for the setup (agent_runtimes.manager). A Jarvis agent
  // with nothing connected yet still starts: it takes the last chat seat.
  const needsProvider = external && !option;
  // The seats are still being read: creating now would leave the provider to
  // the backend's last chat seat, which may be billed per use.
  // The runtimes answer which ways of paying work (a plan or only a key), so
  // the default waits for them on every runtime.
  const seatsPending = (!option && menu.loading) || runtimes.isLoading;
  const accountBlocked = Boolean(account && accountProvider === option?.seat.provider.id
    && (accountValue !== account || menu.loading || menu.failed));
  const selectedModelsFailed = Boolean(option && menu.modelErrors?.includes(option.seat.provider.id));
  const ready = !needsProvider && !seatsPending && !accountBlocked && !selectedModelsFailed && (!option || models.length > 0);

  const pick: SeatPick = {
    runtime,
    executionEnvironment: external ? "local" : executionEnvironment,
    provider: option?.seat.provider.id,
    model: option ? modelValue : undefined,
    accountId: option ? accountValue || option.accountId : undefined,
  };
  const modelLabel = models.find((entry) => entry.id === modelValue)?.label || modelValue || defaultModelLabel;

  return {
    runtimes, menu, choices, chosen, option, models, accounts, modelValue, accountValue,
    runtime, external, executionEnvironment, ready, seatsPending, accountBlocked, selectedModelsFailed, pick, modelLabel,
    defaultModelLabel,
    setRuntime: (next: AgentRuntime) => { setRuntimeState(next); setAccount(""); },
    setProvider: (next: string) => { setProviderId(next); setAccount(""); },
    setAccess: (kind: string) => {
      if (chosen) {
        setPickedAccess((known) => ({ ...known, [chosen.id]: kind }));
        rememberAccess(chosen.id, kind as ModelAccess);
      }
      setAccount("");
    },
    setAccount: (next: string) => { if (option) setAccountProvider(option.seat.provider.id); setAccount(next); setModel(""); },
    setModel,
    setExecutionEnvironment,
  };
}

export type CreateSeat = ReturnType<typeof useCreateSeat>;

/**
 * The access a fresh agent starts on: the one picked in this dialog, else a
 * remembered one unless it bills per use while a plan or a local model is
 * there, else the cheapest (`pickableOption`). Blank, starter and template
 * agents all start here, so each gets the same cost-safe default.
 */
export function startingOption(choice: ProviderChoice, picked?: string, remembered?: string): AccessOption | null {
  if (picked) return pickableOption(choice, picked);
  const cheapest = pickableOption(choice);
  const recalled = remembered ? pickableOption(choice, remembered) : null;
  if (recalled && cheapest && billedPerUse(recalled) && !billedPerUse(cheapest)) return cheapest;
  return recalled ?? cheapest;
}

/** The sentence that explains how the picked access pays. */
function accessHint(t: (key: string) => string, option: AccessOption): string {
  return t(option.extraUsage ? "society.create_agent.access_extra_usage" : `society.create_agent.access_hint_${option.kind}`);
}

/** The full choice: runtime cards, provider, access, login and model. */
export function SeatFields({ seat, disabled }: { seat: CreateSeat; disabled: boolean }) {
  const t = useT();
  const { chosen, option, choices, menu, runtimes, models, accounts } = seat;
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5 text-sm">
        <span className="font-medium">{t("society.create_agent.type_label")}</span>
        <RuntimeChoice value={seat.runtime} onChange={seat.setRuntime} disabled={disabled} />
        <p className="text-xs text-muted-foreground" data-testid="create-agent-runtime-note">
          {t(`agent_create.runtime_note.${seat.runtime}`)}
        </p>
      </div>

      <div className="flex flex-col gap-1.5 text-sm">
        <span className="font-medium">{t("society.create_agent.provider_label")}</span>
        {chosen ? (
          <BrandedSelect
            value={chosen.id}
            onValueChange={seat.setProvider}
            ariaLabel={t("society.create_agent.provider_label")}
            disabled={disabled}
            testId="create-agent-provider"
            options={choices.map((choice) => ({
              value: choice.id,
              label: choice.label,
              // A coding CLI wears its own mark: a letter in a box is not a logo.
              icon: choice.mark
                ? <AgentMark agent={choice.mark} label={choice.label} logoUrl={choice.logoUrl} variant="plain" size="sm" />
                : <ProviderLogo providerId={choice.logo} label={choice.label} size="sm" />,
            }))}
          />
        ) : (
          <p className="text-xs text-muted-foreground">
            {menu.loading
              ? t("society.create.catalog_loading")
              : t(seat.external ? "society.create_agent.no_provider" : "society.create_agent.no_provider_jarvis")}
          </p>
        )}
      </div>

      {chosen ? (
        <AccessChoice
          options={chosen.options}
          value={option?.kind ?? ""}
          hint={option ? accessHint(t, option) : ""}
          warn={billedPerUse(option)}
          disabled={disabled}
          onChange={seat.setAccess}
        />
      ) : null}

      {!seat.external ? <SandboxChoice value={seat.executionEnvironment} onChange={seat.setExecutionEnvironment} disabled={disabled} /> : null}
      {chosen && option && accounts.length ? (
        <div className="flex flex-col gap-1.5 text-sm">
          <span className="font-medium">{t("society.create_agent.account_label")}</span>
          <BrandedSelect
            value={seat.accountValue}
            onValueChange={seat.setAccount}
            ariaLabel={t("society.create_agent.account_label")}
            disabled={disabled}
            testId="create-agent-account"
            options={[
              { value: "", label: t("society.create_agent.active_account") },
              ...accounts.map((entry) => ({ value: entry.id, label: entry.label, hint: accountHint(entry) })),
            ]}
          />
        </div>
      ) : null}

      {chosen && option ? (
        <div className="flex flex-col gap-1.5 text-sm">
          <div className="flex items-center justify-between gap-2">
            <span className="font-medium">{t("society.create_agent.model_label")}</span>
            <button type="button" disabled={disabled || menu.refreshing} onClick={() => void Promise.all([menu.refresh(), runtimes.refetch()])}
              aria-label={t("society.chat.model_refresh")} title={t("society.chat.model_refresh")}
              className="rounded p-1 text-muted-foreground hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50">
              {menu.refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <RefreshCw className="h-3.5 w-3.5" aria-hidden />}
            </button>
          </div>
          <BrandedSelect
            value={seat.modelValue}
            onValueChange={seat.setModel}
            ariaLabel={t("society.create_agent.model_label")}
            placeholder={t("agent_chat.no_models")}
            disabled={disabled || seat.accountBlocked || models.length === 0}
            testId="create-agent-model"
            searchPlaceholder={models.length >= SEARCH_FROM ? t("society.create_agent.model_search") : undefined}
            options={models.map((entry) => ({
              value: entry.id,
              label: entry.label || entry.id || seat.defaultModelLabel,
            }))}
          />
          <p className="text-xs text-muted-foreground">{t("society.create_agent.model_hint")}</p>
          {menu.refreshing ? <p role="status" className="text-xs text-muted-foreground">{t("society.chat.models_loading")}</p> : null}
          {menu.refreshFailed || seat.selectedModelsFailed ? <p role="alert" className="text-xs text-destructive">{t("society.chat.model_load_failed")}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

/**
 * The seat as one quiet line — "Runs on OpenAI · GPT-5.5 · API key" — that
 * opens into the full choice. The starter and import paths lead with the
 * job; the seat is already right for most people and one click away.
 */
export function SeatSummary({ seat, disabled }: { seat: CreateSeat; disabled: boolean }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const { chosen, option } = seat;
  const parts = [
    t(`society.runtime.${seat.runtime}`),
    chosen?.label,
    option ? seat.modelLabel : null,
    option ? t(`society.create.kind_${option.kind}`) : null,
  ].filter(Boolean);
  // Still reading the seats: not a missing choice, just a moment.
  const blocked = !seat.ready && !seat.seatsPending;
  return (
    <section className="rounded-[10px] border border-border bg-sheen/[0.02]" data-testid="create-agent-seat-summary">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        disabled={disabled}
        className="flex w-full items-center gap-3 rounded-[10px] px-3 py-2.5 text-left transition-colors hover:bg-secondary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-border bg-background">
          {chosen?.mark
            ? <AgentMark agent={chosen.mark} label={chosen.label} logoUrl={chosen.logoUrl} variant="plain" size="sm" />
            : chosen ? <ProviderLogo providerId={chosen.logo} label={chosen.label} size="sm" /> : null}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-xs text-muted-foreground">{t("agent_create.seat.runs_on")}</span>
          <span className={cn("block truncate text-sm", blocked ? "text-warning" : "text-foreground")}>
            {seat.seatsPending ? t("society.create.catalog_loading") : blocked ? t("agent_create.seat.needs_choice") : parts.join(" · ")}
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
          {t(open ? "agent_create.seat.hide" : "agent_create.seat.change")}
          <ChevronDown className={cn("size-3.5 transition-transform duration-200 motion-reduce:transition-none", open && "rotate-180")} aria-hidden />
        </span>
      </button>
      {billedPerUse(option) && option ? (
        // Billed per use: said in plain sight, not only behind "Change".
        <p className="flex items-start gap-1.5 border-t border-border px-3 py-2 text-xs text-warning" data-testid="create-agent-seat-cost">
          <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
          <span>{accessHint(t, option)}</span>
        </p>
      ) : null}
      {open || blocked ? (
        <div className="border-t border-border px-3 py-4">
          <SeatFields seat={seat} disabled={disabled} />
        </div>
      ) : null}
    </section>
  );
}
