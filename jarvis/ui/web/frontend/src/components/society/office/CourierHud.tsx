/**
 * The pilot's HUD while the courier flies: speed, height, throttle and boost,
 * the flight assist and camera (both switchable here or by key), the landing
 * assist, and stepping out once the ship stands on the pad. H shows every
 * binding; Escape opens the settings, where any key can be rebound, pitch
 * inverted and the engine's volume set. Theme tokens only, so light and dark
 * mode both read.
 */
import { useEffect, useState } from "react";
import { useT } from "@/i18n";
import { DEFAULT_BINDINGS, FLIGHT_ACTIONS, keyLabel, rebind, type FlightAction } from "./courierControls";
import { FLIGHT } from "./courierFlight";
import { useCourier } from "./courierStore";
import "./courierHud.css";

/** The keys of one action as a pilot reads them, each label once (left and right Shift are both "Shift"). */
function keysLabel(codes: readonly string[]): string {
  return [...new Set(codes.map(keyLabel))].join(" / ") || "–";
}

function Meter({ label, value }: { label: string; value: number }) {
  return (
    <div className="courier-meter">
      <span>{label}</span>
      <i aria-hidden><b style={{ width: `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%` }} /></i>
    </div>
  );
}

export function CourierHud() {
  const t = useT();
  const telemetry = useCourier((s) => s.telemetry);
  const assist = useCourier((s) => s.assist);
  const view = useCourier((s) => s.view);
  const helpOpen = useCourier((s) => s.helpOpen);
  const settingsOpen = useCourier((s) => s.settingsOpen);
  const bindings = useCourier((s) => s.bindings);
  const mouseLocked = useCourier((s) => s.mouseLocked);
  const store = useCourier.getState;
  const kmh = Math.round(telemetry.speed * 3.6);
  const boostShare = Math.min(1, telemetry.speed / FLIGHT.boost);
  const keysOf = (action: FlightAction) => keysLabel(bindings[action]);
  return (
    <>
      <div className="courier-hud office-card" data-office-ui role="group" aria-label={t("society.office.flight_hud")}>
        <div className="courier-speed" aria-live="off">
          <strong>{kmh}</strong><span>km/h</span>
          <i className="courier-speed-arc" aria-hidden style={{ ["--share" as string]: boostShare }} />
        </div>
        <div className="courier-readouts">
          <span>{t("society.office.flight_altitude")} <strong>{Math.round(telemetry.altitude)} m</strong></span>
          <Meter label={t("society.office.flight_throttle")} value={telemetry.throttle} />
          <Meter label={t("society.office.flight_boost")} value={telemetry.charge} />
        </div>
        <div className="courier-actions">
          <button type="button" className="office-chip" aria-pressed={assist === "simulation"}
            onClick={() => store().setPrefs({ assist: assist === "arcade" ? "simulation" : "arcade" })}
            title={`${t("society.office.flight_assist")} (${keysOf("assist")})`}>
            {t(assist === "arcade" ? "society.office.flight_assist_arcade" : "society.office.flight_assist_simulation")}
          </button>
          <button type="button" className="office-chip" onClick={() => store().setPrefs({ view: view === "chase" ? "cockpit" : "chase" })}
            title={keysOf("camera")}>
            {t(view === "chase" ? "society.office.flight_view_chase" : "society.office.flight_view_cockpit")}
          </button>
          {telemetry.landed
            ? <button type="button" className="office-chip courier-primary" onClick={() => store().requestExit()}>{t("society.office.flight_leave")}</button>
            : telemetry.autopilot
              ? <span className="courier-status">{t("society.office.flight_landing")}</span>
              : <button type="button" className="office-chip" onClick={() => store().requestLanding()} title={keysOf("land")}>{t("society.office.flight_land")}</button>}
          <button type="button" className="office-chip" aria-pressed={helpOpen} onClick={() => store().set({ helpOpen: !helpOpen })}>{t("society.office.flight_help")}</button>
          <button type="button" className="office-chip" onClick={() => store().set({ settingsOpen: true })}>{t("society.office.flight_settings")}</button>
        </div>
        {telemetry.landed
          ? <p className="office-hint">{t("society.office.flight_landed_hint").replace("{0}", keysOf("exit"))}</p>
          : <p className="office-hint">{t(mouseLocked ? "society.office.flight_mouse_on" : "society.office.flight_mouse_hint")}</p>}
      </div>
      {helpOpen && !settingsOpen && (
        <div className="courier-help office-card" data-office-ui>
          <p className="office-subhead">{t("society.office.flight_keys")}</p>
          <dl>
            {FLIGHT_ACTIONS.map((action) => (
              <div key={action}><dt>{t(`society.office.flight_action_${action}`)}</dt><dd><kbd>{keysOf(action)}</kbd></dd></div>
            ))}
          </dl>
          <p className="office-hint">{t("society.office.flight_gamepad")}</p>
        </div>
      )}
      {settingsOpen && <CourierSettings />}
    </>
  );
}

function CourierSettings() {
  const t = useT();
  // One selector per choice: the telemetry ticking eight times a second does not redraw the settings.
  const assist = useCourier((s) => s.assist);
  const view = useCourier((s) => s.view);
  const invertPitch = useCourier((s) => s.invertPitch);
  const volume = useCourier((s) => s.volume);
  const bindings = useCourier((s) => s.bindings);
  const store = useCourier.getState;
  const [capturing, setCapturing] = useState<FlightAction | null>(null);
  useEffect(() => {
    if (!capturing) return;
    const onKey = (event: KeyboardEvent) => {
      event.preventDefault();
      event.stopPropagation();
      if (event.key !== "Escape") store().setBindings(rebind(store().bindings, capturing, event.code));
      setCapturing(null);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [capturing, store]);
  return (
    <div className="courier-settings office-card" role="dialog" aria-modal="false" aria-label={t("society.office.flight_settings")} data-office-ui>
      <div className="courier-settings-head">
        <strong>{t("society.office.flight_settings")}</strong>
        <button type="button" className="office-icon-button" aria-label={t("society.office.flight_close")} onClick={() => store().set({ settingsOpen: false })}>×</button>
      </div>
      <div className="courier-settings-row">
        <span>{t("society.office.flight_assist")}</span>
        {(["arcade", "simulation"] as const).map((a) => (
          <button key={a} type="button" className="office-chip" aria-pressed={assist === a} onClick={() => store().setPrefs({ assist: a })}>
            {t(`society.office.flight_assist_${a}`)}
          </button>
        ))}
      </div>
      <div className="courier-settings-row">
        {(["chase", "cockpit"] as const).map((v) => (
          <button key={v} type="button" className="office-chip" aria-pressed={view === v} onClick={() => store().setPrefs({ view: v })}>
            {t(`society.office.flight_view_${v}`)}
          </button>
        ))}
      </div>
      <label className="courier-settings-row">
        <input type="checkbox" checked={invertPitch} onChange={(e) => store().setPrefs({ invertPitch: e.target.checked })} />
        <span>{t("society.office.flight_invert")}</span>
      </label>
      <label className="courier-settings-row">
        <span>{t("society.office.flight_volume")}</span>
        <input type="range" min={0} max={1} step={0.05} value={volume} onChange={(e) => store().setPrefs({ volume: Number(e.target.value) })} />
      </label>
      <p className="office-subhead">{t("society.office.flight_keys")}</p>
      <div className="courier-bindings">
        {FLIGHT_ACTIONS.map((action) => (
          <div key={action} className="courier-binding">
            <span>{t(`society.office.flight_action_${action}`)}</span>
            <button type="button" className="office-chip" aria-pressed={capturing === action} onClick={() => setCapturing(action)}>
              {capturing === action ? t("society.office.flight_rebind") : keysLabel(bindings[action])}
            </button>
          </div>
        ))}
      </div>
      <button type="button" className="office-link" onClick={() => store().setBindings({ ...DEFAULT_BINDINGS })}>{t("society.office.flight_reset")}</button>
    </div>
  );
}
