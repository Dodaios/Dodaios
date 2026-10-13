/**
 * The quiet parts of the office HUD: a small icon toolbar (follow, overview,
 * places, list, help), the one prompt for whatever the person can use right
 * now, and the control hints a first-time visitor sees once. Theme tokens
 * only; nothing here polls or animates on its own.
 */
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { CircleHelp, List, LocateFixed, MapPin, Maximize, SquareTerminal } from "lucide-react";
import { useT } from "@/i18n";
import type { OfficeLayout } from "./officeLayout";
import { OFFICE_CONTROLS } from "./officeControls";
import { useOfficeStore } from "./officeStore";
import { KeyCaps, PlacesList } from "./ReceptionPanel";

export { stationAction, stationLabel } from "./stationText";

function Tool({ label, shortcut, children, ...rest }: {
  label: string; shortcut?: string; children: ReactNode;
} & Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "children" | "aria-label">) {
  return (
    <button type="button" className="office-tool" aria-label={label} aria-keyshortcuts={shortcut}
      data-tip={shortcut ? `${label} (${shortcut})` : label} {...rest}>
      {children}
    </button>
  );
}

/**
 * The places of this floor, opened from the toolbar: every station as a real
 * button, for pointer and keyboard alike. An opaque card that never grows
 * past the stage; when there is more below, its lower edge fades to say so.
 */
function PlacesCard({ id, layout, focusFirst, onPicked }: { id: string; layout: OfficeLayout; focusFirst: boolean; onPicked: () => void }) {
  const t = useT();
  const scroller = useRef<HTMLDivElement>(null);
  const [more, setMore] = useState(false);
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const check = () => setMore(el.scrollHeight - el.scrollTop - el.clientHeight > 4);
    check();
    el.addEventListener("scroll", check, { passive: true });
    window.addEventListener("resize", check);
    return () => {
      el.removeEventListener("scroll", check);
      window.removeEventListener("resize", check);
    };
  }, [layout]);
  // Opened from the keyboard: land on the first place, so the arrows work at once.
  useEffect(() => {
    if (focusFirst) scroller.current?.querySelector<HTMLElement>("[data-place-open]")?.focus({ preventScroll: true });
  }, [focusFirst]);
  return (
    <div id={id} className="office-places-card" role="group" aria-label={t("society.office.hud_places")} data-more={more || undefined}>
      <div ref={scroller} className="office-places-scroll">
        <PlacesList layout={layout} withReception onPicked={onPicked} />
      </div>
    </div>
  );
}

export function OfficeTools({ layout, follow, onFollow, onOverview, helpOpen, onHelp, list }: {
  layout: OfficeLayout;
  follow: boolean; onFollow: () => void; onOverview: () => void;
  helpOpen: boolean; onHelp: () => void;
  /** The roster this floor belongs to: the agents view, the IDE, or the IDE tab's sessions list; null on a floor without one. */
  list: { label: string; ide: boolean; onOpen: () => void } | null;
}) {
  const t = useT();
  const [places, setPlaces] = useState<{ open: boolean; byKeyboard: boolean }>({ open: false, byKeyboard: false });
  const dock = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const placesId = useId();
  const close = () => {
    setPlaces({ open: false, byKeyboard: false });
    // A row that was pointed at is gone with the card; nothing may stay lit in the world.
    useOfficeStore.getState().setHover(null);
  };
  useEffect(() => {
    if (!places.open) return;
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !dock.current?.contains(event.target)) close();
    };
    document.addEventListener("pointerdown", outside, true);
    return () => document.removeEventListener("pointerdown", outside, true);
  }, [places.open]);
  return (
    <div ref={dock} className="office-hud office-tools-dock" data-office-ui
      onKeyDown={(event) => {
        if (event.key !== "Escape" || !places.open) return;
        event.preventDefault();
        event.stopPropagation();
        close();
        trigger.current?.focus();
      }}>
      <div className="office-tools" role="toolbar" aria-label={t("society.office.hud_tools")}>
        <Tool label={t("society.office.me")} aria-pressed={follow} onClick={onFollow}><LocateFixed aria-hidden /></Tool>
        <Tool label={t("society.office.overview")} onClick={onOverview}><Maximize aria-hidden /></Tool>
        <button ref={trigger} type="button" className="office-tool" aria-label={t("society.office.hud_places")}
          data-tip={places.open ? undefined : t("society.office.hud_places")} aria-expanded={places.open} aria-controls={placesId}
          // A click without a pointer (Enter, Space) came from the keyboard.
          onClick={(event) => (places.open ? close() : setPlaces({ open: true, byKeyboard: event.detail === 0 }))}
          onKeyDown={(event) => {
            if (event.key !== "ArrowDown") return;
            // Arrow down opens the card on its first place, or steps into a card that is already open.
            event.preventDefault();
            event.stopPropagation();
            if (places.open) dock.current?.querySelector<HTMLElement>("[data-place-open]")?.focus();
            else setPlaces({ open: true, byKeyboard: true });
          }}>
          <MapPin aria-hidden />
        </button>
        {list && <Tool label={list.label} onClick={list.onOpen}>{list.ide ? <SquareTerminal aria-hidden /> : <List aria-hidden />}</Tool>}
        <Tool label={t("society.office.guide.hud_button")} shortcut="H" aria-pressed={helpOpen} onClick={onHelp}><CircleHelp aria-hidden /></Tool>
      </div>
      {places.open && <PlacesCard id={placesId} layout={layout} focusFirst={places.byKeyboard} onPicked={close} />}
    </div>
  );
}

/** What the prompt says: how it is triggered, the action, and (for a station) the object it belongs to. */
export interface PromptLine {
  /** `key`: the person stands at it and E uses it. `click`: the pointer rests on it from afar. */
  how: "key" | "click";
  action: string;
  object?: string;
}

/**
 * The one prompt on screen: a key cap, the action, the object's name. A real button, so a click or a tap works too.
 * In a narrow host (`compact`, the IDE side panel) there is no room for both texts: the action is shown whole,
 * wrapping if it must, and the object's name is kept for screen readers only.
 */
export function StationPrompt({ line, onUse, compact = false }: { line: PromptLine; onUse: () => void; compact?: boolean }) {
  const t = useT();
  return (
    <button type="button" className="office-prompt" data-office-ui data-compact={compact || undefined} onClick={onUse}>
      {line.how === "key"
        ? <kbd className="office-key">E</kbd>
        : <kbd className="office-key" data-mouse>{t("society.office.guide.mouse_click")}</kbd>}
      <b>{line.action}</b>
      {line.object && <span className={compact ? "sr-only" : undefined}>{line.object}</span>}
    </button>
  );
}

const HINT_IDS = ["walk", "rotate", "interact", "guide"] as const;

/**
 * The controls, once: shown to someone who has not dismissed them yet,
 * remembered per browser profile (officeSettings). Reception's settings bring
 * them back.
 */
export function ControlHints({ onDismiss }: { onDismiss: () => void }) {
  const t = useT();
  return (
    <section className="office-card office-hints" data-office-ui aria-label={t("society.office.hints_label")}>
      <ul>
        {HINT_IDS.map((id) => {
          const control = OFFICE_CONTROLS.find((c) => c.id === id);
          if (!control) return null;
          // One way to do it is enough for a first hint; the guide lists every alternative.
          return <li key={id}><KeyCaps control={{ keys: control.keys.slice(0, 1) }} />{t(`society.office.hint_${id}`)}</li>;
        })}
      </ul>
      <button type="button" className="office-hints-dismiss" onClick={onDismiss}>{t("society.office.hints_dismiss")}</button>
    </section>
  );
}
