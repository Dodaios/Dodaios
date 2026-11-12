import { useState, type ReactNode } from "react";
import { Laptop, Monitor } from "lucide-react";

import { PANEL_ICON, PANEL_ROW_BUTTON, PanelSection, ShowMore } from "@/components/home/panelParts";
import { useComputers, useThisComputer } from "@/hooks/useComputers";
import { useLocaleChunk, useT } from "@/i18n";
import { useEventStore } from "@/store/events";
import { isLaptopName, MachineIcon } from "@/views/computers/machineKind";

/** How many computers show before the rest folds away. */
export const COMPUTERS_SHOWN = 2;

interface Row {
  id: string;
  name: string;
  /** The line under the name: whose it is, or how its last check went. */
  note: string;
  icon: ReactNode;
  /** The assistant's conversation runs on this one. */
  home: boolean;
}

/**
 * The computers the assistant can work on: this one, and every connected
 * one that is switched on. The computer its conversation runs on leads and
 * wears a green dot; this computer follows. Two show, the rest unfolds.
 * Every row opens the Computers page.
 *
 * `leadComputerId` is the conversation's own placement: empty for this
 * computer, else a connected computer's id.
 */
export function PanelComputers({ leadComputerId }: { leadComputerId: string }) {
  const t = useT();
  const statusReady = useLocaleChunk("computers");
  const computers = useComputers();
  const self = useThisComputer();
  const setActive = useEventStore((s) => s.setActiveSection);
  const [open, setOpen] = useState(false);

  const connected = (computers.data ?? []).filter((computer) => computer.enabled !== false);
  // A placement on a computer that is gone or switched off leaves this one as the home.
  const homeId = connected.some((computer) => computer.id === leadComputerId) ? leadComputerId : "";
  const selfName = self.data?.name || t("sidebar.computer_this");
  const SelfIcon = isLaptopName(selfName) ? Laptop : Monitor;
  const rows: Row[] = [
    {
      id: "",
      name: selfName,
      note: t("sidebar.computer_yours"),
      icon: <SelfIcon aria-hidden strokeWidth={1.75} className={PANEL_ICON} />,
      home: homeId === "",
    },
    ...connected.map((computer) => ({
      id: computer.id,
      name: computer.name,
      note: statusReady ? t(`computers.status_${computer.health.status}`) : "",
      icon: <MachineIcon computer={computer} aria-hidden strokeWidth={1.75} className={PANEL_ICON} />,
      home: computer.id === homeId,
    })),
  ].sort((a, b) => Number(b.home) - Number(a.home));
  const shown = open ? rows : rows.slice(0, COMPUTERS_SHOWN);
  const homeHint = t("sidebar.computer_home");

  return (
    <PanelSection id="computers" title={t("sidebar.computers")}>
      {shown.map((row) => (
        <button key={row.id} type="button" data-testid={`assistant-computer-${row.id || "this"}`} data-home={row.home}
          onClick={() => setActive("computers")} title={row.home ? `${row.name} · ${homeHint}` : row.name}
          className={PANEL_ROW_BUTTON}>
          <span className="relative shrink-0">
            {row.icon}
            {row.home && (
              <span role="img" aria-label={homeHint} data-testid="assistant-computer-home"
                className="absolute -bottom-0.5 -right-0.5 h-2 w-2 rounded-full bg-success ring-2 ring-card" />
            )}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm text-foreground">{row.name}</span>
            {row.note && <span className="block truncate text-sm text-muted-foreground">{row.note}</span>}
          </span>
        </button>
      ))}
      {rows.length > COMPUTERS_SHOWN && (
        <ShowMore testId="assistant-computers-more" open={open} onToggle={() => setOpen((value) => !value)} />
      )}
    </PanelSection>
  );
}
