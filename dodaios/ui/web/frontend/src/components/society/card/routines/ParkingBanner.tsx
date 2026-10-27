/**
 * The one-time note after away-parking paused an agent's routines: resume,
 * keep them paused, or resume and never pause them again. It shows once per
 * park; any answer closes it for good.
 */
import { useState } from "react";
import { MoonStar } from "lucide-react";
import { useT } from "@/i18n";
import { answerParking, type ParkingChoice, type ParkingView } from "./routinesApi";
import { fill } from "./format";

export function ParkingBanner({ agentId, parking, onAnswered }: {
  agentId: string; parking: ParkingView; onAnswered: () => void;
}) {
  const t = useT();
  const own = (key: string) => t(`society.agent_routines.parking.${key}`);
  const [busy, setBusy] = useState<ParkingChoice | null>(null);
  const [error, setError] = useState("");
  const choose = async (choice: ParkingChoice) => {
    setBusy(choice); setError("");
    try { await answerParking(agentId, choice); onAnswered(); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(null); }
  };
  const count = parking.parked_ids.length;
  const button = "rounded-lg px-2.5 py-1 text-[12px] font-medium transition-colors duration-150 disabled:opacity-50";
  return <div role="status" data-testid="routine-parking-banner"
    className="mb-3 rounded-xl border border-warning/30 bg-warning/[0.06] p-3 shadow-[0_1px_2px_rgb(var(--scrim-rgb)/0.06)]">
    <div className="flex items-start gap-2.5">
      <MoonStar size={16} aria-hidden className="mt-0.5 shrink-0 text-warning" />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-[13px] font-semibold leading-tight text-foreground-strong">{own("title")}</p>
        <p className="text-[12px] leading-snug text-foreground-secondary">
          {fill(own(count === 1 ? "body_one" : "body"), { count, unread: parking.unread, days: parking.parked_days })}
        </p>
      </div>
    </div>
    <div className="mt-2.5 flex flex-wrap gap-1.5 pl-[26px]">
      <button type="button" disabled={busy !== null} onClick={() => void choose("keep_running")}
        className={`${button} bg-foreground text-background hover:bg-foreground/90`}>{own("keep_running")}</button>
      <button type="button" disabled={busy !== null} onClick={() => void choose("keep_paused")}
        className={`${button} border border-border bg-background text-foreground hover:bg-secondary`}>{own("keep_paused")}</button>
      <button type="button" disabled={busy !== null} onClick={() => void choose("never_ask")}
        className={`${button} text-muted-foreground hover:bg-secondary hover:text-foreground`}>{own("never_ask")}</button>
    </div>
    {error && <p role="alert" className="mt-2 pl-[26px] text-xs text-destructive">{error}</p>}
  </div>;
}
