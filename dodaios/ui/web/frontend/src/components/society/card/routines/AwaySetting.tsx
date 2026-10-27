/** The away-parking window, as one quiet line under the routine list. */
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useT } from "@/i18n";
import { BrandedSelect } from "@/components/ui/select";
import { answerParking, saveParkingDays, useParkingDays } from "./routinesApi";
import { fill } from "./format";

const CHOICES = [0, 3, 7, 14, 30];

export function AwaySetting({ agentId, neverAsk, onChanged }: { agentId: string; neverAsk: boolean; onChanged: () => void }) {
  const t = useT();
  const own = (key: string) => t(`society.agent_routines.away.${key}`);
  const days = useParkingDays();
  const client = useQueryClient();
  const [error, setError] = useState("");
  if (days.isError || days.data === undefined) return null;
  const value = String(days.data);
  const options = [...new Set([...CHOICES, days.data])].sort((a, b) => a - b)
    .map((n) => ({ value: String(n), label: n === 0 ? own("never") : fill(own("after_days"), { n }) }));
  return <div className="mt-3 flex shrink-0 items-center gap-2 px-3 text-[13px] text-muted-foreground" data-testid="routine-away-setting">
    <span className="min-w-0 flex-1 leading-tight" title={own("hint")}>{neverAsk ? own("off_for_agent") : own("label")}</span>
    {neverAsk ? <button type="button" className="shrink-0 rounded-md px-1.5 py-0.5 text-foreground hover:bg-secondary" onClick={() => {
      setError("");
      void answerParking(agentId, "ask_again").then(onChanged).catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
    }}>{own("turn_on")}</button> : <div className="w-[112px] shrink-0">
      <BrandedSelect value={value} options={options} ariaLabel={own("label")} onValueChange={(next) => {
        setError("");
        void saveParkingDays(Number(next)).then((saved) => {
          client.setQueryData(["society", "routine-parking-days"], saved);
          void client.invalidateQueries({ queryKey: ["society", "routine-activity", agentId] });
          onChanged();
        }).catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
      }} />
    </div>}
    {error && <span role="alert" className="text-destructive">{error}</span>}
  </div>;
}
