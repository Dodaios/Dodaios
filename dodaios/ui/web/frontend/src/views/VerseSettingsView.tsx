/**
 * Settings → Game settings: the Verse's in-game settings menu, in the app.
 *
 * Built like a game's own options screen: tabs across the top, rows with a
 * "‹ value ›" stepper or a filled bar, and a detail column that explains the
 * focused setting, its performance cost and (for the crosshair) a live
 * preview. The options come from the backend catalogue
 * (`dodaios/verse_host/game_settings.py`); every change is written at once and
 * reaches a running Verse live (`settings.changed`).
 */
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { Loader2, RotateCcw, Search } from "lucide-react";
import { Bar, CrosshairPreview, ImpactMeter, KeyCap, Stepper, roundTo } from "@/components/verseSettings/controls";
import "@/components/verseSettings/verseSettings.css";
import { fetchVerseStatus } from "@/components/verseHost/verseHostApi";
import { useLocaleChunk, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import {
  RESERVED_KEYS,
  addToPatch,
  applyPatch,
  fetchCatalogue,
  fetchSettings,
  formatValue,
  keyLabel,
  patchSettings,
  readValue,
  type Catalogue,
  type SettingDef,
  type SettingValue,
  type SettingsPatch,
  type VerseSettings,
} from "@/lib/verseSettingsApi";

const P = "verse_settings";
const SAVE_DELAY_MS = 180;

export function VerseSettingsView() {
  useLocaleChunk("verse_settings");
  const tr = useT();
  const t = useCallback(
    (key: string, vars?: Record<string, string>) => {
      let text = tr(`${P}.${key}`);
      for (const [k, v] of Object.entries(vars ?? {})) text = text.replaceAll(`{${k}}`, v);
      return text;
    },
    [tr],
  );

  const [catalogue, setCatalogue] = useState<Catalogue | null>(null);
  const [settings, setSettings] = useState<VerseSettings | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [tab, setTab] = useState("graphics");
  const [query, setQuery] = useState("");
  const [focusId, setFocusId] = useState<string | null>(null);
  const [listening, setListening] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [live, setLive] = useState(false);

  const load = useCallback(async () => {
    setLoadError(false);
    try {
      const [c, s] = await Promise.all([fetchCatalogue(), fetchSettings()]);
      setCatalogue(c);
      setSettings(s);
    } catch {
      setLoadError(true);
    }
  }, []);

  useEffect(() => {
    void load();
    let alive = true;
    const poll = () =>
      fetchVerseStatus().then(
        (s) => alive && setLive(s.status === "running"),
        () => alive && setLive(false),
      );
    void poll();
    const timer = window.setInterval(poll, 5000);
    // The in-game menu writes the same settings; pick its changes up on return.
    const onFocus = () => void fetchSettings().then((s) => alive && setSettings(s), () => undefined);
    window.addEventListener("focus", onFocus);
    return () => {
      alive = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [load]);

  // ------------------------------------------------------------------ saving
  const pending = useRef<SettingsPatch>({});
  const timer = useRef<number | null>(null);
  const flush = useCallback(async () => {
    timer.current = null;
    const patch = pending.current;
    pending.current = {};
    if (!Object.keys(patch).length) return;
    try {
      setSettings(await patchSettings(patch));
      setSaveError(null);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
      void fetchSettings().then(setSettings, () => undefined);
    }
  }, []);
  useEffect(() => () => void flush(), [flush]);

  const commit = useCallback(
    (patch: SettingsPatch, immediate = false) => {
      setSettings((s) => (s ? applyPatch(s, patch) : s));
      for (const [k, v] of Object.entries(patch)) {
        const prev = pending.current[k];
        pending.current[k] =
          v && typeof v === "object" && prev && typeof prev === "object" ? { ...(prev as object), ...(v as object) } : v;
      }
      if (timer.current) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => void flush(), immediate ? 0 : SAVE_DELAY_MS);
    },
    [flush],
  );

  const byId = useMemo(() => new Map((catalogue?.settings ?? []).map((d) => [d.id, d])), [catalogue]);
  const value = useCallback((def: SettingDef) => readValue(settings, def), [settings]);

  const change = useCallback(
    (def: SettingDef, next: SettingValue) => {
      if (!catalogue) return;
      const patch: SettingsPatch = {};
      addToPatch(patch, def, next);
      if (def.id === "graphics.preset" && typeof next === "string" && next !== "auto" && next !== "custom") {
        for (const id of catalogue.preset_groups) {
          const group = byId.get(id);
          if (group?.options?.includes(next)) addToPatch(patch, group, next);
        }
      } else if (def.tags?.includes("preset")) {
        const preset = byId.get("graphics.preset");
        if (preset && value(preset) !== "custom") {
          addToPatch(patch, preset, "custom");
          setNotice(t("preset_custom_hint"));
        }
      }
      commit(patch, def.kind !== "range");
    },
    [byId, catalogue, commit, t, value],
  );

  const bindKey = useCallback(
    (def: SettingDef, key: string) => {
      setListening(null);
      if (RESERVED_KEYS.has(key)) {
        setNotice(t("key_reserved", { key: keyLabel(key) }));
        return;
      }
      const patch: SettingsPatch = {};
      addToPatch(patch, def, key);
      const old = value(def);
      const other = (catalogue?.settings ?? []).find((d) => d.kind === "key" && d.id !== def.id && value(d) === key);
      if (other && typeof old === "string") {
        addToPatch(patch, other, old);
        setNotice(t("key_swapped", { key: keyLabel(key), action: tr(`${P}.s.${other.id}.label`) }));
      } else {
        setNotice(null);
      }
      commit(patch, true);
    },
    [catalogue, commit, t, tr, value],
  );

  const resetTab = useCallback(() => {
    if (!catalogue) return;
    const patch: SettingsPatch = {};
    for (const def of catalogue.settings) if (def.tab === tab) addToPatch(patch, def, def.default);
    commit(patch, true);
    setConfirmReset(false);
  }, [catalogue, commit, tab]);

  // ------------------------------------------------------------------ view model
  const label = useCallback((def: SettingDef) => tr(`${P}.s.${def.id}.label`), [tr]);
  const optionLabel = useCallback(
    (def: SettingDef, option: string) => {
      if (def.id === "display.resolution" && option !== "native") return option.replace("x", " × ");
      if (def.id === "display.frame_limit" && option !== "unlimited") return `${option} FPS`;
      return tr(`${P}.o.${option}`);
    },
    [tr],
  );
  const shown = useCallback(
    (def: SettingDef, v: SettingValue) => {
      if (def.kind === "toggle") return tr(`${P}.o.${v ? "on" : "off"}`);
      if (def.kind === "choice") return optionLabel(def, String(v));
      if (def.kind === "key") return keyLabel(String(v));
      return formatValue(def, v);
    },
    [optionLabel, tr],
  );

  const q = query.trim().toLowerCase();
  const visible = useMemo(() => {
    if (!catalogue) return [];
    if (q) return catalogue.settings.filter((d) => label(d).toLowerCase().includes(q));
    return catalogue.settings.filter((d) => d.tab === tab);
  }, [catalogue, label, q, tab]);
  const sections = useMemo(() => {
    const out: { key: string; tab: string; section: string; items: SettingDef[] }[] = [];
    for (const def of visible) {
      const key = `${def.tab}/${def.section}`;
      const last = out[out.length - 1];
      if (last?.key === key) last.items.push(def);
      else out.push({ key, tab: def.tab, section: def.section, items: [def] });
    }
    return out;
  }, [visible]);

  const focused = (focusId && byId.get(focusId)) || visible[0] || null;

  useEffect(() => {
    setFocusId(null);
    setConfirmReset(false);
  }, [tab]);

  // Q / E switch tabs, like a game menu (not while typing or binding a key).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (listening || !catalogue) return;
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)) return;
      if (e.ctrlKey || e.altKey || e.metaKey) return;
      const i = catalogue.tabs.indexOf(tab);
      if (e.key === "q" || e.key === "Q") setTab(catalogue.tabs[(i - 1 + catalogue.tabs.length) % catalogue.tabs.length]);
      else if (e.key === "e" || e.key === "E") setTab(catalogue.tabs[(i + 1) % catalogue.tabs.length]);
      else return;
      setQuery("");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [catalogue, listening, tab]);

  const onRowKey = (def: SettingDef, e: ReactKeyboardEvent<HTMLDivElement>) => {
    const d = e.key === "ArrowLeft" ? -1 : e.key === "ArrowRight" ? 1 : 0;
    if (e.key === "Enter" && def.kind === "key") {
      e.preventDefault();
      setListening(def.id);
      return;
    }
    if (!d) return;
    e.preventDefault();
    const v = value(def);
    if (def.kind === "toggle") change(def, !v);
    else if (def.kind === "choice" && def.options) {
      const i = Math.max(0, def.options.indexOf(String(v)));
      change(def, def.options[(i + d + def.options.length) % def.options.length]);
    } else if (def.kind === "range" && typeof v === "number") {
      const step = def.step ?? 1;
      change(def, Math.min(def.max ?? v, Math.max(def.min ?? v, roundTo(v + d * step, step))));
    }
  };

  // ------------------------------------------------------------------ render
  if (loadError) {
    return (
      <div className="vs-root vs-center">
        <p className="vs-muted">{t("load_failed")}</p>
        <button type="button" className="vs-button" onClick={() => void load()}>
          {t("retry")}
        </button>
      </div>
    );
  }
  if (!catalogue || !settings) {
    return (
      <div className="vs-root vs-center">
        <Loader2 className="h-5 w-5 animate-spin opacity-60" />
        <p className="vs-muted">{t("loading")}</p>
      </div>
    );
  }

  const crosshair = (id: string) => {
    const def = byId.get(`hud.crosshair_${id}`);
    return def ? value(def) : undefined;
  };

  return (
    <div className="vs-root" data-testid="verse-settings">
      <header className="vs-header">
        <div>
          <div className="vs-eyebrow">{t("eyebrow")}</div>
          <h1 className="vs-title">{t("title")}</h1>
          <p className="vs-subtitle">{t("subtitle")}</p>
        </div>
        <div className={cn("vs-live", live && "vs-live-on")}>
          <span className="vs-live-dot" />
          {live ? t("live") : t("offline")}
        </div>
      </header>

      <nav className="vs-tabs" role="tablist">
        <span className="vs-keyhint" aria-hidden>
          Q
        </span>
        {catalogue.tabs.map((id) => (
          <button
            key={id}
            role="tab"
            type="button"
            aria-selected={!q && id === tab}
            className={cn("vs-tab", !q && id === tab && "vs-tab-on")}
            onClick={() => {
              setTab(id);
              setQuery("");
            }}
          >
            {t(`tabs.${id}`)}
          </button>
        ))}
        <span className="vs-keyhint" aria-hidden>
          E
        </span>
        <label className="vs-search">
          <Search className="h-3.5 w-3.5 opacity-60" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("search")} aria-label={t("search")} />
        </label>
      </nav>

      <div className="vs-body">
        <div className="vs-list">
          {sections.length === 0 ? <p className="vs-muted vs-empty">{t("no_results", { query })}</p> : null}
          {sections.map((sec) => (
            <section key={sec.key} className="vs-section">
              <h2 className="vs-section-title">
                {q ? <span className="vs-section-tab">{t(`tabs.${sec.tab}`)} · </span> : null}
                {t(`sections.${sec.section}`)}
              </h2>
              {sec.items.map((def) => {
                const v = value(def);
                const changed = v !== def.default;
                return (
                  <div
                    key={def.id}
                    role="group"
                    tabIndex={0}
                    aria-label={label(def)}
                    data-setting={def.id}
                    className={cn("vs-row", focused?.id === def.id && "vs-row-on")}
                    onMouseEnter={() => setFocusId(def.id)}
                    onFocus={() => setFocusId(def.id)}
                    onKeyDown={(e) => onRowKey(def, e)}
                  >
                    <span className="vs-row-label">
                      {label(def)}
                      {changed ? <span className="vs-changed" title={t("changed")} /> : null}
                    </span>
                    <span className="vs-row-control">
                      {def.kind === "choice" && def.options ? (
                        <Stepper options={def.options} value={String(v)} label={(o) => optionLabel(def, o)} onChange={(o) => change(def, o)} />
                      ) : def.kind === "toggle" ? (
                        <Stepper
                          options={["off", "on"]}
                          value={v ? "on" : "off"}
                          label={(o) => tr(`${P}.o.${o}`)}
                          onChange={(o) => change(def, o === "on")}
                        />
                      ) : def.kind === "range" ? (
                        <Bar
                          value={Number(v)}
                          min={def.min ?? 0}
                          max={def.max ?? 1}
                          step={def.step ?? 1}
                          text={formatValue(def, v)}
                          ariaLabel={label(def)}
                          onChange={(n) => change(def, n)}
                        />
                      ) : (
                        <KeyCap
                          value={String(v)}
                          listening={listening === def.id}
                          onListen={() => setListening(def.id)}
                          onPick={(k) => bindKey(def, k)}
                          onCancel={() => setListening(null)}
                          pressText={t("press_key")}
                        />
                      )}
                    </span>
                  </div>
                );
              })}
            </section>
          ))}
        </div>

        <aside className="vs-detail" aria-live="polite">
          {focused ? (
            <>
              <div className="vs-detail-eyebrow">
                {t(`tabs.${focused.tab}`)} · {t(`sections.${focused.section}`)}
              </div>
              <h3 className="vs-detail-title">{label(focused)}</h3>
              {focused.section === "crosshair" ? (
                <div className="vs-crosshair" aria-label={t("crosshair_preview")}>
                  <CrosshairPreview
                    style={String(crosshair("style") ?? "cross_dot")}
                    color={String(crosshair("color") ?? "amber")}
                    size={Number(crosshair("size") ?? 4)}
                    thickness={Number(crosshair("thickness") ?? 2)}
                    gap={Number(crosshair("gap") ?? 3)}
                    outline={Boolean(crosshair("outline") ?? true)}
                  />
                </div>
              ) : null}
              {focused.kind !== "key" ? <p className="vs-detail-desc">{tr(`${P}.s.${focused.id}.desc`)}</p> : null}
              {focused.kind === "key" ? <p className="vs-detail-desc">{t("press_key_hint")}</p> : null}
              <dl className="vs-facts">
                <div>
                  <dt>{t("default")}</dt>
                  <dd>{shown(focused, focused.default)}</dd>
                </div>
                {focused.impact ? (
                  <div>
                    <dt>{t("impact")}</dt>
                    <dd className="vs-impact-row">
                      <ImpactMeter level={focused.impact} />
                      {t(`impact_${focused.impact}`)}
                    </dd>
                  </div>
                ) : null}
              </dl>
              {focused.restart ? <p className="vs-detail-note">{t("restart")}</p> : null}
              {value(focused) !== focused.default ? (
                <button
                  type="button"
                  className="vs-link"
                  onClick={() => (focused.kind === "key" ? bindKey(focused, String(focused.default)) : change(focused, focused.default))}
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  {t("reset_one")}
                </button>
              ) : null}
            </>
          ) : null}
        </aside>
      </div>

      <footer className="vs-footer">
        <div className="vs-footer-msg" role="status">
          {saveError ? <span className="vs-error">{t("save_failed", { error: saveError })}</span> : notice}
        </div>
        {!q ? (
          confirmReset ? (
            <div className="vs-confirm">
              <span>{t("reset_tab_confirm", { tab: t(`tabs.${tab}`) })}</span>
              <button type="button" className="vs-button vs-button-primary" onClick={resetTab}>
                {t("reset_confirm_yes")}
              </button>
              <button type="button" className="vs-button" onClick={() => setConfirmReset(false)}>
                {t("reset_confirm_no")}
              </button>
            </div>
          ) : (
            <button type="button" className="vs-button" onClick={() => setConfirmReset(true)}>
              <RotateCcw className="h-3.5 w-3.5" />
              {t("reset_tab")}
            </button>
          )
        ) : null}
      </footer>
    </div>
  );
}

export default VerseSettingsView;
