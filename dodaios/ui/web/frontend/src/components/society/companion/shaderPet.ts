/**
 * A user shader pet (`jarvis-shader-pet/1`). The fragment file is the
 * author's `main`. This wraps it so the app owns the uniforms, and so a
 * state change draws the old look and the new one and mixes them.
 *
 * The bans mirror `dodaios/ui/pets/shader.py`. The server is the authority
 * on save; this check is what the create dialog can say before the upload.
 */
import { releaseWebglContext } from "@/hooks/useWebglSurface";
import { PET_STATES, type PetState } from "@/lib/petStates";
import { readVoiceInputLevel } from "@/lib/voiceInputLevel";
import { voiceOutputLevelRef } from "@/lib/voiceOutputLevel";
/** How long a state change takes to finish mixing, in seconds. */
export const SHADER_BLEND_S = 0.33;

/** The sphere every shader pet shares. The fragment file is the author's. */
export const PET_VERTEX_SHADER = /* glsl */ `
varying vec3 vLocal;
varying vec3 vNormal;
varying vec3 vView;
void main() {
  vec4 world = modelMatrix * vec4(position, 1.0);
  vLocal = position;
  vNormal = normalize(mat3(modelMatrix) * normal);
  vView = cameraPosition - world.xyz;
  gl_Position = projectionMatrix * viewMatrix * world;
}`;

export interface ShaderBlend {
  from: number;
  to: number;
  /** 0 is entirely the previous state, 1 is entirely the next. */
  blend: number;
}

const BANNED_DIRECTIVES = ["#include", "#version", "#extension", "#define", "#pragma", "#undef"];
const BANNED_WORDS = ["sampler", "uniform", "varying", "attribute", "while", "precision"];
const ANY_FOR = /\bfor\s*\(/g;
/** Same counter in the initializer, the test and the increment, then a brace body. */
const CONST_FOR = /\bfor\s*\(\s*int\s+([A-Za-z_]\w*)\s*=\s*\d+\s*;\s*\1\s*<\s*(\d+)\s*;\s*\1\s*\+\+\s*\)\s*\{/g;
/** One loop of 32 inside a loop of 5 is Wisp Swarm. 32×32 is not. */
const MAX_LOOP_BOUND = 32;
const MAX_LOOP_PRODUCT = MAX_LOOP_BOUND * 5;

/** Drop line continuations and comments so `wh\\\nile` cannot hide `while`. */
function scanSource(source: string): string {
  return source.replace(/\\\r?\n/g, "").replace(/\/\/[^\n]*|\/\*[\s\S]*?\*\//g, " ");
}

function braceBody(source: string, openAt: number): string | null {
  if (source[openAt] !== "{") return null;
  let depth = 0;
  for (let index = openAt; index < source.length; index += 1) {
    const char = source[index];
    if (char === "{") depth += 1;
    else if (char === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(openAt + 1, index);
    }
  }
  return null;
}

function indexWritten(body: string, name: string): boolean {
  const ident = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  // Same pattern as dodaios/ui/pets/shader.py `_index_written`.
  return new RegExp(
    `(?:\\+\\+|--)\\s*(?<![\\w.])${ident}(?![\\w.])|(?<![\\w.])${ident}\\s*(?:\\+\\+|--|[+\\-*/%]=|(?<![=!<>])=(?!=))`,
  ).test(body);
}

function loopError(source: string): string | null {
  ANY_FOR.lastIndex = 0;
  CONST_FOR.lastIndex = 0;
  const loops = source.match(ANY_FOR)?.length ?? 0;
  const bounded = [...source.matchAll(CONST_FOR)];
  if (loops !== bounded.length) {
    return "A for loop must count a fixed number of times, like 'for (int i = 0; i < 8; i++)'.";
  }
  const opens: { bound: number; depth: number }[] = [];
  let depth = 0;
  let cursor = 0;
  const positions = new Map(bounded.map((match) => [match.index ?? 0, match]));
  while (cursor < source.length) {
    const match = positions.get(cursor);
    if (match) {
      const bound = Number(match[2]);
      if (bound > MAX_LOOP_BOUND) return `A for loop may run at most ${MAX_LOOP_BOUND} times.`;
      let product = bound;
      for (const parent of opens) product *= parent.bound;
      if (product > MAX_LOOP_PRODUCT) {
        return `Nested for loops may run at most ${MAX_LOOP_PRODUCT} times together.`;
      }
      const body = braceBody(source, match[0].length + (match.index ?? 0) - 1);
      if (body === null) return "A for loop needs a brace body.";
      if (indexWritten(body, match[1] ?? "")) {
        return "A for loop cannot change its counter inside the body.";
      }
      opens.push({ bound, depth: depth + 1 });
      cursor = (match.index ?? 0) + match[0].length;
      depth += 1;
      continue;
    }
    const char = source[cursor];
    if (char === "{") depth += 1;
    else if (char === "}") {
      depth -= 1;
      while (opens.length > 0 && depth < opens[opens.length - 1].depth) opens.pop();
    }
    cursor += 1;
  }
  return null;
}

export function shaderStateIndex(state: PetState): number {
  const index = PET_STATES.indexOf(state);
  return index < 0 ? 0 : index;
}

/**
 * Loudness for `uLevel`, 0..1. Talking reads the assistant's voice and
 * listening reads the microphone. Every other state is silent, so a stale
 * sample cannot keep the pet moving.
 */
export function shaderVoiceLevel(state: PetState, now = performance.now()): number {
  if (state === "listening") return readVoiceInputLevel(now);
  if (state === "talking") return voiceOutputLevelRef.current ?? 0;
  return 0;
}

/** Advance the mix. A new state restarts it from the one on screen. */
export function stepShaderBlend(current: ShaderBlend, stateIndex: number, dt: number, reduced: boolean): void {
  if (stateIndex !== current.to) {
    current.from = current.to;
    current.to = stateIndex;
    current.blend = reduced ? 1 : 0;
  }
  if (reduced) {
    current.blend = 1;
    return;
  }
  if (current.blend < 1) current.blend = Math.min(1, current.blend + dt / SHADER_BLEND_S);
}

/** The same sentences as the Python loader, for a file that has not been uploaded yet. */
export function shaderSourceError(source: string): string | null {
  if (!source.trim()) return "The shader is empty.";
  if (new TextEncoder().encode(source).length > 16 * 1024) return "The shader is larger than 16 KB.";
  const scanned = scanSource(source);
  for (const directive of BANNED_DIRECTIVES) {
    if (scanned.includes(directive)) return `The shader cannot use ${directive}.`;
  }
  for (const word of BANNED_WORDS) {
    // No trailing boundary: "sampler" has to catch "sampler2D".
    if (new RegExp(`\\b${word}`).test(scanned)) return `The shader cannot use '${word}'.`;
  }
  if (!/\bvoid\s+main\s*\(/.test(scanned)) return "The shader needs a main function.";
  return loopError(scanned);
}

/**
 * The author's main, called twice per pixel: once for the state being left
 * and once for the state being entered. `uBlend` mixes the two colours.
 */
export function wrapPetFragment(source: string): string {
  const body = source.replace(/\bvoid\s+main\s*\(/, "void petMain(");
  // Three.js adds the precision line. A second one is a compile error.
  // uLevel is a macro, like uState: each pass writes petLevel before petMain.
  // The uniforms stay uLevel (the state being entered) and uLevelFrom.
  return `uniform float uTime;
uniform float uState;
uniform float uStateFrom;
uniform float uBlend;
uniform float uLevel;
uniform float uLevelFrom;
varying vec3 vLocal;
varying vec3 vNormal;
varying vec3 vView;
float petState;
float petLevel;
#define uState petState
#define uLevel petLevel
${body}
#undef uLevel
#undef uState
void main() {
  petLevel = uLevelFrom;
  petState = uStateFrom;
  petMain();
  vec4 petFrom = gl_FragColor;
  petLevel = uLevel;
  petState = uState;
  petMain();
  gl_FragColor = mix(petFrom, gl_FragColor, clamp(uBlend, 0.0, 1.0));
}
`;
}

/**
 * Compile the wrapped fragment. The vertex here is only a stand-in: the
 * real one is PET_VERTEX_SHADER, and three.js fills in its matrices.
 * `null` when it compiles. No WebGL is an error string: the create dialog
 * treats null as success (`shaderSourceError(text) ?? compilePetShader(text)`).
 */
const COMPILE_VERTEX = `attribute vec3 position;
varying vec3 vLocal;
varying vec3 vNormal;
varying vec3 vView;
void main() {
  vLocal = position;
  vNormal = position;
  vView = vec3(0.0, 0.0, 1.0);
  gl_Position = vec4(position, 1.0);
}
`;

const NO_WEBGL = "This browser has no WebGL, so the shader cannot be checked.";

export function compilePetShader(source: string): string | null {
  const canvas = document.createElement("canvas");
  let gl: WebGLRenderingContext | null = null;
  try {
    gl = canvas.getContext("webgl");
  } catch {
    gl = null;
  }
  if (!gl) return NO_WEBGL;
  try {
    const fragment = gl.createShader(gl.FRAGMENT_SHADER);
    const vertex = gl.createShader(gl.VERTEX_SHADER);
    if (!fragment || !vertex) return NO_WEBGL;
    gl.shaderSource(fragment, `precision mediump float;\n${wrapPetFragment(source)}`);
    gl.shaderSource(vertex, COMPILE_VERTEX);
    gl.compileShader(fragment);
    gl.compileShader(vertex);
    const fragmentOk = gl.getShaderParameter(fragment, gl.COMPILE_STATUS);
    const vertexOk = gl.getShaderParameter(vertex, gl.COMPILE_STATUS);
    const log = !fragmentOk
      ? gl.getShaderInfoLog(fragment)
      : !vertexOk
        ? gl.getShaderInfoLog(vertex)
        : null;
    gl.deleteShader(fragment);
    gl.deleteShader(vertex);
    return log && log.trim() ? log.trim() : fragmentOk && vertexOk ? null : "The shader did not compile.";
  } finally {
    // dispose() does not exist on a raw context; loseContext hands the slot back.
    releaseWebglContext(canvas);
  }
}
