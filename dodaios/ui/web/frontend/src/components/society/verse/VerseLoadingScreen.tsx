/**
 * The Verse's loading screen: a full-bleed key art with a big "Loading" title,
 * a tip and a progress bar laid over it, shown while the ship opens the first
 * time (code chunk, deck manifest, deck plate). It fades out once the deck is
 * on screen.
 *
 * Kept free of three.js and the stage's other modules so the lazy-loading
 * fallbacks in front of the stage can show it too. All instances share one
 * clock, so the bar keeps going instead of restarting when the fallback hands
 * over to the stage.
 */
import { useEffect, useRef, useState } from "react";
import { useT } from "@/i18n";
import "./verseLoading.css";

export const LOADING_ART = "/verse/loading.webp";

/** True once the key art is decoded; later instances show it without the fade. */
let artLoaded = false;
/** When the first loading screen appeared; shared by every instance. */
let startedAt: number | null = null;
/** One tip per opening, the same in every instance. */
let tipIndex = 0;
const TIP_COUNT = 3;
/** A clock older than this belongs to an opening that was abandoned. */
const STALE_MS = 30_000;

/** Eases toward 92 % within a few seconds; the last bit waits for the real "ready". */
function guessProgress(elapsedMs: number): number {
  return 0.92 * (1 - Math.exp(-elapsedMs / 2200));
}

/** Starts fetching the key art early (on hover over the Verse tab), so the screen never opens blank. */
export function preloadLoadingArt(): void {
  if (typeof Image === "undefined") return;
  const img = new Image();
  img.fetchPriority = "high";
  img.src = LOADING_ART;
}

interface Props {
  /** True once the deck is on screen: the bar fills and the screen fades out. */
  ready?: boolean;
  /** Called after the fade-out, when the screen can be removed. */
  onGone?: () => void;
}

const FADE_MS = 520;
/** A deck that loads in a blink would only flash the screen; it stays at least this long. */
const MIN_SHOW_MS = 1200;

export function VerseLoadingScreen({ ready = false, onGone }: Props) {
  const t = useT();
  // Checked once per instance: a fresh opening starts the clock, a hand-over keeps it.
  useState(() => {
    if (startedAt === null || performance.now() - startedAt > STALE_MS) {
      startedAt = performance.now();
      tipIndex = Math.floor(Math.random() * TIP_COUNT);
    }
    return null;
  });
  const title = t("society.office.loading_title");
  const subtitle = t("society.office.title");
  const tip = t(`society.office.loading_tip_${tipIndex + 1}`);
  const [progress, setProgress] = useState(() => guessProgress(performance.now() - (startedAt ?? 0)));
  const [leaving, setLeaving] = useState(false);
  // The art fades in once fully decoded; a half-loaded image would paint top-down.
  const [art, setArt] = useState(artLoaded);
  const onArt = () => { artLoaded = true; setArt(true); };
  const gone = useRef(onGone);
  gone.current = onGone;

  useEffect(() => {
    if (ready) return;
    const timer = setInterval(() => setProgress(guessProgress(performance.now() - (startedAt ?? 0))), 120);
    return () => clearInterval(timer);
  }, [ready]);

  useEffect(() => {
    if (!ready) return;
    const hold = Math.max(0, (startedAt ?? 0) + MIN_SHOW_MS - performance.now());
    const fill = setTimeout(() => setProgress(1), hold);
    // Let the full bar show for a beat, then fade.
    const fade = setTimeout(() => setLeaving(true), hold + 260);
    const done = setTimeout(() => {
      startedAt = null;
      gone.current?.();
    }, hold + 260 + FADE_MS);
    return () => { clearTimeout(fill); clearTimeout(fade); clearTimeout(done); };
  }, [ready]);

  const percent = Math.round(progress * 100);
  return (
    <div className="verse-loading" data-leaving={leaving} role="status" aria-live="polite" aria-busy={!ready}>
      <div className="verse-loading-blur" aria-hidden />
      <img className="verse-loading-art" fetchPriority="high" src={LOADING_ART} alt="" aria-hidden data-loaded={art} onLoad={onArt} decoding="async" draggable={false} />
      <div className="verse-loading-shade" aria-hidden />
      <div className="verse-loading-copy">
        {subtitle && <span className="verse-loading-sub">{subtitle}</span>}
        {title && <span className="verse-loading-title">{title}</span>}
      </div>
      {tip && <p className="verse-loading-tip">{tip}</p>}
      <div className="verse-loading-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
        <i style={{ transform: `scaleX(${progress})` }} />
        <span className="verse-loading-percent" aria-hidden>{percent}%</span>
      </div>
    </div>
  );
}
