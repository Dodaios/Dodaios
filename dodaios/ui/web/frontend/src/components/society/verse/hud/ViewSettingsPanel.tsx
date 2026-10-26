/**
 * The eye-level views' settings: mouse sensitivity, an inverted vertical
 * axis, the field of view in third and in first person, and the render
 * quality. Changes apply at once and stay in this
 * browser (`viewSettings`).
 */
import { useId, useRef } from "react";
import { fill } from "@/i18n";
import { LOOK_SENSITIVITY, SHOULDER } from "../engine/realtime/shoulderRig";
import { useViewSettings, type QualityChoice } from "../engine/realtime/viewSettings";
import { VerseDialog } from "./VerseDialog";

const QUALITIES: readonly QualityChoice[] = ["auto", "high", "low"];

interface Props {
  t: (key: string) => string;
  /** The tier the eye-level view renders at now ("high" or "low"); empty while it is not on screen. */
  tier: string;
  onClose: () => void;
}

export function ViewSettingsPanel({ t, tier, onClose }: Props) {
  const sensitivity = useViewSettings((s) => s.sensitivity);
  const invertY = useViewSettings((s) => s.invertY);
  const quality = useViewSettings((s) => s.quality);
  const fovThird = useViewSettings((s) => s.fovThird);
  const fovFirst = useViewSettings((s) => s.fovFirst);
  const set = useViewSettings((s) => s.set);
  const reset = useViewSettings((s) => s.reset);
  const first = useRef<HTMLInputElement>(null);
  const id = useId();
  return (
    <VerseDialog title={t("verse.settings.title")} closeLabel={t("verse.card.close")} onClose={onClose} className="verse-form" initialFocus={first}>
      <div className="verse-form-body">
        <div className="verse-field">
          <label className="verse-setting-head" htmlFor={`${id}-sensitivity`}>
            <span className="verse-label">{t("verse.settings.sensitivity")}</span>
            <span className="verse-setting-value">{sensitivity.toFixed(2)}×</span>
          </label>
          <input
            ref={first}
            id={`${id}-sensitivity`}
            type="range"
            className="verse-range"
            min={LOOK_SENSITIVITY.min}
            max={LOOK_SENSITIVITY.max}
            step={0.05}
            value={sensitivity}
            onChange={(e) => set({ sensitivity: Number(e.target.value) })}
          />
        </div>
        <div className="verse-setting-row">
          <span className="verse-label" id={`${id}-invert`}>{t("verse.settings.invert_y")}</span>
          <button
            type="button"
            role="switch"
            aria-checked={invertY}
            aria-labelledby={`${id}-invert`}
            className="verse-switch"
            onClick={() => set({ invertY: !invertY })}
          >
            <i aria-hidden />
          </button>
        </div>
        {([["fovThird", fovThird, "verse.settings.fov_third"], ["fovFirst", fovFirst, "verse.settings.fov_first"]] as const).map(([key, value, label]) => (
          <div className="verse-field" key={key}>
            <label className="verse-setting-head" htmlFor={`${id}-${key}`}>
              <span className="verse-label">{t(label)}</span>
              <span className="verse-setting-value">{Math.round(value)}°</span>
            </label>
            <input
              id={`${id}-${key}`}
              type="range"
              className="verse-range"
              min={SHOULDER.minHfovDeg}
              max={SHOULDER.maxHfovDeg}
              step={1}
              value={value}
              onChange={(e) => set({ [key]: Number(e.target.value) })}
            />
          </div>
        ))}
        <div className="verse-field">
          <span className="verse-label" id={`${id}-quality`}>{t("verse.settings.quality")}</span>
          <div className="verse-seg" role="group" aria-labelledby={`${id}-quality`}>
            {QUALITIES.map((q) => (
              <button key={q} type="button" className="verse-btn" aria-pressed={quality === q} onClick={() => set({ quality: q })}>
                {t(`verse.settings.quality_${q}`)}
              </button>
            ))}
          </div>
          <p className="verse-form-note">
            {t("verse.settings.quality_note")}
            {(tier === "high" || tier === "low") && <> {fill(t("verse.settings.quality_now"), { tier: t(`verse.settings.quality_${tier}`) })}</>}
          </p>
        </div>
        <p className="verse-form-note">{t("verse.settings.mouse_lock")}</p>
      </div>
      <footer className="verse-form-foot">
        <button type="button" className="verse-btn" onClick={reset}>{t("verse.settings.reset")}</button>
      </footer>
    </VerseDialog>
  );
}
