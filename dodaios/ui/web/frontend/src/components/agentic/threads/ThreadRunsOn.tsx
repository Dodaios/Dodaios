/**
 * Where a thread's turns run: this computer, or one of the connected
 * computers (the same list and picker the grid's panes use). Collapsed to one
 * quiet line; nothing shows at all until a computer is connected.
 */
import { useState } from "react";
import { Server } from "lucide-react";
import { RunOnPicker } from "@/components/agentic/RunOnPicker";
import { useComputerChoiceList } from "@/hooks/useComputers";
import { fill, useT } from "@/i18n";

export function ThreadRunsOn({
  computerId,
  onChange,
  locked,
}: {
  computerId: string;
  onChange: (computerId: string) => void;
  locked: boolean;
}) {
  const t = useT();
  const { computers } = useComputerChoiceList();
  const [open, setOpen] = useState(false);
  if (computers.length === 0 && !computerId) return null;
  const current = computers.find((computer) => computer.id === computerId);
  return (
    <div className="px-3 pt-1 text-xs text-muted-foreground" data-testid="thread-runs-on">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 hover:bg-secondary/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Server aria-hidden className="h-3.5 w-3.5" />
        {current ? fill(t("ide_threads.runs_on_computer"), { computer: current.name }) : t("ide_threads.runs_on")}
      </button>
      {open && (
        <div className="mt-2 max-w-xl">
          <RunOnPicker
            value={computerId || null}
            disabled={locked}
            onChange={(id) => {
              onChange(id ?? "");
              setOpen(false);
            }}
          />
        </div>
      )}
    </div>
  );
}
