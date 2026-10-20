import { SectionWindowButton } from "@/components/layout/SectionWindowButton";
import * as Dialog from "@radix-ui/react-dialog";
import { useRef, useState } from "react";
import { X } from "lucide-react";
import { useT } from "@/i18n";
import { isComboboxPanelEvent } from "@/components/ui/combobox";
import { PluginsView } from "@/views/PluginsView";
import { SkillsView } from "@/views/SkillsView";
import { McpsView } from "@/views/McpsView";
import { ExtensionsSidebar } from "@/views/plugins/ExtensionsSidebar";

/** The catalog floats over the user's current work; nested setup stays inside. */
export type PluginArea = "plugins" | "mcps" | "skills";

export function PluginsDialog({ onClose, area = "plugins", onAreaChange, standalone = false }: {
  onClose: () => void;
  area?: PluginArea;
  standalone?: boolean;
  onAreaChange?: (area: PluginArea) => void;
}) {
  const t = useT();
  const content = useRef<HTMLDivElement>(null);
  const opener = useRef(document.activeElement);
  const [ownArea, setOwnArea] = useState<PluginArea>(area);
  const current = onAreaChange ? area : ownArea;
  // The open plugin page lives here, not in the plugin view: the sidebar's
  // installed list opens it from any area.
  const [pluginId, setPluginId] = useState<string | null>(null);
  // Bumped when "Plugins" is chosen in the sidebar, so the directory returns
  // to its home page instead of staying wherever it was left.
  const [directoryVisit, setDirectoryVisit] = useState(0);
  const showArea = (next: PluginArea) => {
    setOwnArea(next);
    onAreaChange?.(next);
  };
  const frame = (
    <div className="flex min-h-0 flex-1 flex-col md:flex-row">
      <ExtensionsSidebar
        area={current}
        selectedPluginId={current === "plugins" ? pluginId : null}
        onArea={(next) => {
          setPluginId(null);
          if (next === "plugins") setDirectoryVisit((visit) => visit + 1);
          showArea(next);
        }}
        onOpenPlugin={(id) => {
          setPluginId(id);
          showArea("plugins");
        }}
      />
      <div data-plugin-pane className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        {!standalone && (
          <div className="absolute right-3 top-2.5 z-10 flex items-center gap-1">
            <SectionWindowButton />
            <Dialog.Close asChild>
              <button type="button" aria-label={t("common.close")} className="grid h-8 w-8 place-items-center rounded-lg text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <X className="h-4 w-4" aria-hidden />
              </button>
            </Dialog.Close>
          </div>
        )}
        {current === "plugins" && <PluginsView key={directoryVisit} selectedId={pluginId} onSelect={setPluginId} />}
        {current === "skills" && <div className="min-h-0 flex-1 overflow-hidden pt-10"><SkillsView /></div>}
        {current === "mcps" && <div className="min-h-0 flex-1 overflow-hidden pt-10"><McpsView /></div>}
      </div>
    </div>
  );
  if (standalone) return <div data-testid="plugin-catalog-window" className="flex h-full min-h-0 flex-col">{frame}</div>;
  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-x-0 bottom-0 top-8 z-40 jarvis-nav-surface" />
        <Dialog.Content
          data-testid="plugin-catalog-dialog"
          ref={content}
          aria-describedby={undefined}
          onOpenAutoFocus={(event) => {
            // Typing should search at once. An area without a search field
            // keeps the focus on the window itself, so no sidebar entry is
            // ringed as if it had been chosen.
            const search = content.current?.querySelector<HTMLInputElement>('[data-plugin-pane] input[type="search"]');
            event.preventDefault();
            (search ?? content.current)?.focus({ preventScroll: true });
          }}
          onCloseAutoFocus={(event) => {
            const previous = opener.current;
            const target = previous instanceof HTMLElement && previous.isConnected && previous !== document.body
              ? previous
              : document.querySelector<HTMLElement>('[data-testid="nav-row-plugins"]')
                ?? document.querySelector<HTMLElement>("main");
            if (!target) return;
            // This route-driven dialog has no Radix Trigger to restore focus to.
            event.preventDefault();
            const needsTabIndex = target.tagName === "MAIN" && !target.hasAttribute("tabindex");
            if (needsTabIndex) target.setAttribute("tabindex", "-1");
            target.focus({ preventScroll: true });
            if (needsTabIndex) target.removeAttribute("tabindex");
          }}
          onPointerDownOutside={(event) => {
            if (isComboboxPanelEvent(event) || content.current?.querySelector('[aria-modal="true"]')) {
              event.preventDefault();
            }
          }}
          onFocusOutside={(event) => {
            if (isComboboxPanelEvent(event) || content.current?.querySelector('[aria-modal="true"]')) {
              event.preventDefault();
            }
          }}
          onInteractOutside={(event) => {
            if (isComboboxPanelEvent(event) || content.current?.querySelector('[aria-modal="true"]')) {
              event.preventDefault();
            }
          }}
          onEscapeKeyDown={(event) => {
            // Escape belongs to whatever is open inside the window first: a
            // credential dialog, a menu, or a search field with text in it.
            const inner = content.current?.querySelector('[aria-modal="true"], [role="menu"]');
            const local = document.activeElement?.closest("[data-escape-local]");
            if (inner || local) event.preventDefault();
          }}
          // The whole window below the title bar, like Settings: the section is a
          // place to work in, not a box over the previous one.
          className="jarvis-nav-surface fixed inset-x-0 bottom-0 top-8 z-40 flex flex-col overflow-hidden text-foreground outline-none [&_[aria-modal=true]]:overflow-y-auto"
        >
          <Dialog.Title className="sr-only">{t("plugins_view.title")}</Dialog.Title>
          {frame}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
