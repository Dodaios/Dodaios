import { useId } from "react";
import { motion, useReducedMotion, type TargetAndTransition } from "framer-motion";
import type { VoiceState } from "@/store/events";
import { cn } from "@/lib/utils";

/**
 * A holographic neural core for the assistant's home screen.
 *
 * The diagram is deliberately SVG and CSS rather than a continuously rendered
 * 3D scene: it stays crisp at every deck size, follows the live voice state,
 * and keeps the home screen light on laptop graphics. Its animation is purely
 * decorative; all task and voice status remains available as text elsewhere
 * in the deck.
 */
const MOTION: Record<VoiceState, { animate: TargetAndTransition; duration: number }> = {
  idle: {
    animate: { scale: [1, 1.018, 1], filter: ["brightness(0.92)", "brightness(1.08)", "brightness(0.92)"] },
    duration: 5.2,
  },
  connecting: {
    animate: { scale: [1, 1.008, 1], filter: ["brightness(0.82)", "brightness(1.2)", "brightness(0.82)"] },
    duration: 1.3,
  },
  listening: {
    animate: { scale: [1, 1.025, 1], filter: ["brightness(1)", "brightness(1.35)", "brightness(1)"] },
    duration: 1.6,
  },
  thinking: {
    animate: { scale: [1, 1.014, 1], filter: ["brightness(0.95)", "brightness(1.28)", "brightness(0.95)"] },
    duration: 1.15,
  },
  speaking: {
    animate: { scale: [1, 1.022, 1], filter: ["brightness(1)", "brightness(1.3)", "brightness(1)"] },
    duration: 1.35,
  },
  paused: { animate: { scale: 1, filter: "brightness(0.72) saturate(0.65)" }, duration: 0 },
  error: { animate: { scale: 1, filter: "brightness(0.62) saturate(0.55)" }, duration: 0 },
};

const NODES: ReadonlyArray<readonly [number, number, number]> = [
  [128, 28, 2.2], [99, 33, 1.7], [157, 34, 1.8], [76, 49, 1.6], [119, 51, 2],
  [141, 53, 1.7], [181, 51, 1.5], [58, 73, 1.8], [89, 70, 1.5], [108, 76, 1.8],
  [133, 72, 2.1], [157, 77, 1.6], [177, 72, 1.7], [199, 82, 1.7], [49, 103, 1.6],
  [72, 96, 1.9], [96, 105, 1.5], [119, 98, 2.1], [143, 103, 1.7], [167, 98, 1.9],
  [190, 105, 1.5], [207, 112, 1.6], [60, 130, 1.8], [84, 126, 1.6], [108, 133, 2],
  [131, 124, 2.2], [153, 133, 1.8], [177, 126, 1.6], [198, 134, 1.7], [72, 155, 1.5],
  [99, 153, 1.7], [125, 160, 2.2], [150, 154, 1.8], [178, 156, 1.6], [91, 175, 1.6],
  [116, 183, 1.8], [140, 183, 1.8], [165, 175, 1.6], [105, 199, 1.5], [151, 199, 1.5],
];

const EDGES: ReadonlyArray<readonly [number, number]> = [
  [0, 1], [0, 2], [1, 3], [1, 4], [2, 4], [2, 5], [2, 6], [3, 7], [3, 8], [4, 8],
  [4, 9], [4, 10], [5, 10], [5, 11], [6, 11], [6, 12], [6, 13], [7, 14], [7, 15],
  [8, 9], [8, 15], [8, 16], [9, 10], [9, 16], [9, 17], [10, 11], [10, 17], [10, 18],
  [11, 12], [11, 18], [11, 19], [12, 13], [12, 19], [12, 20], [13, 20], [13, 21],
  [14, 15], [14, 22], [15, 16], [15, 22], [15, 23], [16, 17], [16, 23], [16, 24],
  [17, 18], [17, 24], [17, 25], [18, 19], [18, 25], [18, 26], [19, 20], [19, 26],
  [19, 27], [20, 21], [20, 27], [20, 28], [21, 28], [22, 23], [22, 29], [23, 24],
  [23, 29], [23, 30], [24, 25], [24, 30], [24, 31], [25, 26], [25, 31], [25, 32],
  [26, 27], [26, 32], [26, 33], [27, 28], [27, 33], [28, 33], [29, 30], [29, 34],
  [30, 31], [30, 34], [30, 35], [31, 32], [31, 35], [31, 36], [32, 33], [32, 36],
  [32, 37], [33, 37], [34, 35], [34, 38], [35, 36], [35, 38], [36, 37], [36, 39],
  [37, 39], [38, 39],
];

function NeuralNetwork() {
  const id = useId().replaceAll(":", "");
  const fillId = `${id}-neural-core-fill`;
  const glowId = `${id}-neural-core-glow`;
  return (
    <svg data-testid="neural-core-network" viewBox="0 0 256 236" className="neural-core-network absolute inset-0 h-full w-full" aria-hidden="true">
      <defs>
        <radialGradient id={fillId} cx="50%" cy="42%" r="62%">
          <stop offset="0" stopColor="#21d9f4" stopOpacity="0.2" />
          <stop offset="0.68" stopColor="#1387c9" stopOpacity="0.07" />
          <stop offset="1" stopColor="#0c4b86" stopOpacity="0" />
        </radialGradient>
        <filter id={glowId} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="2.5" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>

      <path className="neural-core-hull" d="M128 19 C106 16 91 24 79 36 C61 40 49 56 49 75 C37 88 39 107 48 118 C44 134 54 148 67 154 C70 171 85 181 102 182 C109 197 119 205 128 205 C137 205 147 197 154 182 C171 181 186 171 189 154 C202 148 212 134 208 118 C217 107 219 88 207 75 C207 56 195 40 177 36 C165 24 150 16 128 19 Z" fill={`url(#${fillId})`} />
      <g className="neural-core-orrery">
        <ellipse cx="128" cy="119" rx="111" ry="31" transform="rotate(-27 128 119)" />
        <ellipse cx="128" cy="119" rx="103" ry="29" transform="rotate(34 128 119)" />
        <ellipse cx="128" cy="119" rx="116" ry="34" transform="rotate(7 128 119)" />
      </g>
      <g className="neural-core-facets">
        <path d="M128 21 L177 37 L207 75 L208 118 L189 154 L154 182 L128 205 L102 182 L67 154 L48 118 L49 75 L79 37 Z" />
        <path d="M79 37 L119 51 L128 21 L157 34 L177 37 L157 77 L181 51 L199 82 L167 98 L190 105 L177 126 L198 134 L178 156 L165 175 L151 199 L140 183 L128 205 L116 183 L105 199 L91 175 L78 156 L58 130 L84 126 L60 130 L72 96 L49 103 L58 73 L89 70 L76 49 Z" />
        <path d="M99 33 L108 76 L119 98 L108 133 L99 153 L116 183 M157 34 L143 72 L143 103 L153 133 L150 154 L140 183" />
      </g>
      <path className="neural-core-midline" d="M128 25 C123 50 134 62 127 82 C121 103 136 116 128 137 C122 154 134 169 128 197" />

      <g className="neural-core-latitude">
        <ellipse cx="128" cy="91" rx="79" ry="23" />
        <ellipse cx="128" cy="128" rx="83" ry="25" />
        <ellipse cx="128" cy="160" rx="65" ry="20" />
      </g>
      <g className="neural-core-longitude">
        <path d="M128 21 C88 55 85 109 128 203" />
        <path d="M128 21 C168 55 171 109 128 203" />
        <path d="M79 37 C111 80 112 145 102 182" />
        <path d="M177 37 C145 80 144 145 154 182" />
      </g>

      <g className="neural-core-links">
        {EDGES.map(([from, to]) => {
          const [x1, y1] = NODES[from];
          const [x2, y2] = NODES[to];
          return <line key={`${from}-${to}`} x1={x1} y1={y1} x2={x2} y2={y2} />;
        })}
      </g>
      <g className="neural-core-nodes" filter={`url(#${glowId})`}>
        {NODES.map(([cx, cy, r]) => (
          <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r={r} />
        ))}
      </g>
      <circle className="neural-core-nucleus-halo" cx="128" cy="119" r="29" />
      <circle className="neural-core-nucleus" cx="128" cy="119" r="10" />
    </svg>
  );
}

export function DodaiosOrb({
  size,
  voiceState,
  active = false,
  className,
}: {
  size: number;
  voiceState: VoiceState;
  active?: boolean;
  className?: string;
}) {
  const reduced = useReducedMotion() ?? false;
  const spec = MOTION[voiceState] ?? MOTION.idle;
  const looping = spec.duration > 0;

  return (
    <div
      data-testid="jarvis-orb"
      data-voice={voiceState}
      data-active={active ? "true" : "false"}
      className={cn("neural-core relative select-none", className)}
      style={{ width: size, height: size }}
    >
      <div className="neural-core-backlight absolute inset-0 rounded-full" aria-hidden="true" />
      <motion.div
        className="relative h-full w-full"
        animate={reduced ? undefined : spec.animate}
        transition={
          reduced
            ? undefined
            : looping
              ? { duration: spec.duration, repeat: Infinity, ease: "easeInOut" }
              : { duration: 0.4 }
        }
      >
        <NeuralNetwork />
      </motion.div>
    </div>
  );
}
