import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Laptop, Plus, Server } from "lucide-react";
import { useComputerChoiceList } from "@/hooks/useComputers";
import { useEventStore } from "@/store/events";
import { cn } from "@/lib/utils";
import { fill, useT } from "@/i18n";
import { ThreadMenuHeading, ThreadMenuItem, ThreadMenuSeparator, ThreadPopover } from "./ThreadPopover";

/**
 * Which machine a thread's turns run on: this computer, or one of the
 * connected computers (the list the grid's panes use). Always on screen, so
 * the place to connect a computer is found before one exists.
 */
export function ThreadMachineChip({
  computerId,
  onChange,
  draft,
  locked,
  className,
}: {
  /** "" = this computer. */
  computerId: string;
  onChange: (computerId: string) => void;
  draft: boolean;
  /** The agent is working: its turn cannot move to another machine. */
  locked: boolean;
  className: string;
}) {
  const t = useT();
  const { computers, loaded } = useComputerChoiceList();
  const setActiveSection = useEventStore((state) => state.setActiveSection);
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLButtonElement | null>(null);
  const usable = computers.filter((computer) => computer.health.status !== "provisioning" && computer.enabled !== false);
  const current = computers.find((computer) => computer.id === computerId);

  // A remembered computer that was removed since: a new thread falls back to
  // this computer, rather than failing on its first message.
  const missing = draft && loaded && computerId !== "" && !usable.some((computer) => computer.id === computerId);
  useEffect(() => { if (missing) onChange(""); }, [missing, onChange]);

  const pick = (id: string) => {
    setOpen(false);
    if (id !== computerId) onChange(id);
  };

  return <>
    <button ref={anchor} type="button" className={className} disabled={locked} aria-haspopup="menu" aria-expanded={open}
      data-testid="thread-machine" onClick={() => setOpen(!open)}
      title={current ? fill(t("ide_threads.runs_on_computer"), { computer: current.name }) : t("ide_threads.runs_on")}>
      {current ? <Server aria-hidden className="h-3.5 w-3.5 shrink-0" /> : <Laptop aria-hidden className="h-3.5 w-3.5 shrink-0" />}
      <span className="max-w-[150px] truncate">{current ? current.name : t("workspace_launcher.run_on.local")}</span>
      <ChevronDown aria-hidden className="h-3 w-3 shrink-0" />
    </button>
    <ThreadPopover anchor={anchor} open={open} onClose={() => setOpen(false)} label={t("ide_threads.runs_on")} side="top" width={290}>
      <div role="menu">
        <ThreadMenuHeading>{t("ide_threads.machine_local")}</ThreadMenuHeading>
        <ThreadMenuItem icon={<Laptop className="h-3.5 w-3.5" />} label={t("workspace_launcher.run_on.local")} selected={!current}
          hint={!current ? <Check className="h-3.5 w-3.5" /> : undefined} onSelect={() => pick("")} />
        {usable.length > 0 && <>
          <ThreadMenuHeading>{t("ide_threads.machine_computers")}</ThreadMenuHeading>
          {usable.map((computer) => {
            const online = computer.health.status === "online";
            return <ThreadMenuItem key={computer.id} icon={<Server className="h-3.5 w-3.5" />} selected={computer.id === computerId}
              label={<span className="flex min-w-0 items-center gap-2">
                <span className="truncate">{computer.name}</span>
                <span aria-hidden className={cn("h-1.5 w-1.5 shrink-0 rounded-full", online ? "bg-accent" : "bg-foreground-faint")} />
              </span>}
              hint={computer.id === computerId ? <Check className="h-3.5 w-3.5" /> : online ? undefined : t("ide_threads.machine_offline")}
              onSelect={() => pick(computer.id)} />;
          })}
        </>}
        <ThreadMenuSeparator />
        <ThreadMenuItem icon={<Plus className="h-3.5 w-3.5" />} label={t("ide_threads.connect_computer")}
          onSelect={() => { setOpen(false); setActiveSection("computers"); }} />
      </div>
    </ThreadPopover>
  </>;
}
