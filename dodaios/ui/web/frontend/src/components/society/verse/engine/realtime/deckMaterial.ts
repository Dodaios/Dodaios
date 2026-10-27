/**
 * Materials of the eye-level deck: the light Cycles baked plus a live
 * specular layer.
 *
 * The bake holds all diffuse light, albedo included (`radiance = albedo ×
 * irradiance + emission`, scene linear, "rgbm2" in the lightmap pages), so
 * every surface draws that radiance and adds only what depends on the eye:
 * reflections of its room's probe, box-projected so ceiling panels mirror in
 * the black deck where they hang, with the material's roughness, metalness,
 * specular level and clear coat. Dielectrics get a black base colour (their
 * diffuse light is already in the bake); metals keep their tint for the
 * specular. Deck floors add their plate seams and smudged coat close up.
 *
 * `patchDeckShader` is a pure string transform of three.js's physical
 * shader (tested in deckMaterial.test.ts); `makeDeckMaterial` builds one
 * material instance per (material, room, page) chunk.
 */
import {
  Color, CustomBlending, DoubleSide, MeshPhysicalMaterial, MeshStandardMaterial, OneFactor, OneMinusSrcAlphaFactor, ShaderChunk, Vector3,
  type Texture, type WebGLProgramParametersWithUniforms,
} from "three";
import type { RealtimeMaterial } from "../../content/deck";

/** Runtime close-up layers (`detail` in the manifest). */
export const DETAIL_KINDS = ["none", "deck_plates", "painted", "metal"] as const;

/**
 * Depth ties between surfaces in one plane. The kit lays many faces flush on
 * each other (a raised floor's edge on a wall, a recess panel on wall paint,
 * a beam on the hull plating, two rooms' walls back to back), and without an
 * order the GPU picked one surface per pixel and per frame, so whole strips
 * of wall flickered as the camera moved. Each surface is moved back along
 * its view ray by a small fraction of its distance (the picture does not
 * move, only the depth). Every material of a deck gets its own step, in
 * layers: keys, lights and screens in front, then trims, structure, walls and
 * floors, the hull, and back faces behind them all. A fraction of the
 * distance stays above the depth buffer's step out to about 25 m (8 cm near
 * plane), unlike a polygon offset, which measured worse: its slope term
 * pushed surfaces that sit millimetres apart into new ties.
 */
export const PUSH_STEP = 2e-5;
/** Back faces: behind every front face of a deck with up to 100 materials. */
export const BACK_FACE_PUSH = 2.5e-3;

/** 0 hull, 1 walls, floors, ceilings, 2 structure and bodies, 3 trims and small parts, 4 keys, indicators, lights, screens. Pure. */
export function surfaceLayer(material: string): number {
  const m = material.replace(/^M_(TMP_[A-Za-z]+_)?/, "");
  if (/^Hull/.test(m)) return 0;
  if (/^(Wall|Floor|Ceiling|Hangar_Deck|Deck_)/.test(m)) return 1;
  if (/^(Struct|Console_Body|Crate|Container|Recess)/.test(m)) return 2;
  if (/^(Indicator|Console_Keys|Screen|Light|Emit|Glass)/.test(m) || /Lamp/.test(m)) return 4;
  return 3;
}

/** Each material's place in the deck's depth order: 0 in front, by layer (front first), then name. Pure. */
export function depthOrder(materials: Iterable<string>): Map<string, number> {
  const names = [...new Set(materials)].sort((a, b) => surfaceLayer(b) - surfaceLayer(a) || (a < b ? -1 : a > b ? 1 : 0));
  return new Map(names.map((n, i) => [n, i]));
}

/** How far a material at `order` moves back, as a fraction of its distance. Pure. */
export function depthPush(order: number): number {
  return order * PUSH_STEP;
}

const DEPTH_PUSH = /* glsl */ `
{
  float versePushNow = verseDepthPush;
  if ( dot( transformedNormal, - mvPosition.xyz ) < 0.0 ) versePushNow = ${BACK_FACE_PUSH.toExponential()};
  gl_Position = projectionMatrix * vec4( mvPosition.xyz * ( 1.0 + versePushNow ), 1.0 );
}
`;

const LIGHTS_FRAGMENT_MAPS = [
  "#if defined( USE_ENVMAP ) && defined( RE_IndirectSpecular )",
  "  radiance += getIBLRadiance( geometryViewDir, geometryNormal, material.roughness );",
  "  #ifdef USE_CLEARCOAT",
  "    clearcoatRadiance += getIBLRadiance( geometryViewDir, geometryClearcoatNormal, material.clearcoatRoughness );",
  "  #endif",
  "#endif",
].join("\n");

const FRAGMENT_HEAD = /* glsl */ `
varying vec3 vVerseWorld;
uniform float verseRange;
uniform float verseBakedGain;
uniform float verseCoatBias;
uniform float verseBoxOn;
uniform vec3 verseBoxMin;
uniform vec3 verseBoxMax;
uniform vec3 verseProbePos;

// rgbm2: m = a^2 * range, rgb = c^2 * m.
vec3 verseDecode( vec4 t ) {
  return t.rgb * t.rgb * ( t.a * t.a * verseRange );
}

// Parallax-corrected reflection direction (world space) inside the room's box.
// A fragment past the box (a doorway, a lift alcove, a sill a hair outside) grows
// the box to hold it, so the projection never jumps to the unprojected direction:
// that jump drew lights far from where they hang, cut off at a hard line.
vec3 verseBoxProject( vec3 dir, float roughness ) {
  if ( verseBoxOn < 0.5 ) return dir;
  vec3 p = vVerseWorld;
  vec3 boxMin = min( verseBoxMin, p - 0.02 );
  vec3 boxMax = max( verseBoxMax, p + 0.02 );
  vec3 d = vec3(
    abs( dir.x ) < 1e-5 ? 1e-5 : dir.x,
    abs( dir.y ) < 1e-5 ? 1e-5 : dir.y,
    abs( dir.z ) < 1e-5 ? 1e-5 : dir.z
  );
  vec3 far = max( ( boxMax - p ) / d, ( boxMin - p ) / d );
  float t = max( 0.0, min( min( far.x, far.y ), far.z ) );
  vec3 projected = normalize( p + dir * t - verseProbePos );
  return normalize( mix( projected, dir, roughness * roughness ) );
}

float verseHash( vec2 p ) {
  p = fract( p * vec2( 123.34, 456.21 ) );
  p += dot( p, p + 45.32 );
  return fract( p.x * p.y );
}

float verseNoise( vec2 p ) {
  vec2 i = floor( p );
  vec2 f = fract( p );
  vec2 u = f * f * ( 3.0 - 2.0 * f );
  return mix( mix( verseHash( i ), verseHash( i + vec2( 1.0, 0.0 ) ), u.x ),
              mix( verseHash( i + vec2( 0.0, 1.0 ) ), verseHash( i + vec2( 1.0, 1.0 ) ), u.x ), u.y );
}

float verseFbm( vec2 p ) {
  return 0.5 * verseNoise( p ) + 0.3 * verseNoise( p * 2.03 + 7.1 ) + 0.2 * verseNoise( p * 4.11 + 3.7 );
}

#ifdef VERSE_DECK_PLATES
// Deck plates 2.4 m (x) by 1.2 m (z) on the ship's world grid: satin steel joints and bolts.
float verseSeam( vec3 w ) {
  vec2 cell = vec2( w.x / 2.4, w.z / 1.2 );
  vec2 f = fract( cell );
  vec2 edge = min( f, 1.0 - f ) * vec2( 2.4, 1.2 );
  float d = min( edge.x, edge.y );
  float aa = max( fwidth( d ), 1e-4 );
  float seam = 1.0 - smoothstep( 0.0025 - aa, 0.0025 + aa, d );
  float bolt = length( abs( edge - vec2( 0.05 ) ) );
  float baa = max( fwidth( bolt ), 1e-4 );
  return max( seam, 1.0 - smoothstep( 0.0085 - baa, 0.0085 + baa, bolt ) );
}
#endif
`;

const DETAIL_PROPERTIES = /* glsl */ `
#ifdef VERSE_DECK_PLATES
  float verseJoint = verseSeam( vVerseWorld );
  roughnessFactor = mix( roughnessFactor, 0.32, verseJoint );
  metalnessFactor = mix( metalnessFactor, 1.0, verseJoint );
  diffuseColor.rgb = mix( diffuseColor.rgb, vec3( 0.2, 0.2, 0.205 ), verseJoint );
#endif
#if defined( VERSE_PAINTED ) || defined( VERSE_METAL )
  {
    // Satin paint breaks its reflections up softly; steel in fine streaks along the piece.
    vec3 verseFace = abs( normalize( cross( dFdx( vVerseWorld ), dFdy( vVerseWorld ) ) ) );
    vec2 q = verseFace.x > verseFace.y && verseFace.x > verseFace.z ? vVerseWorld.zy
      : ( verseFace.y > verseFace.z ? vVerseWorld.xz : vVerseWorld.xy );
    #ifdef VERSE_METAL
      float verseBreak = verseFbm( vec2( q.x * 36.0, q.y * 1.4 ) );
    #else
      float verseBreak = verseFbm( q * 2.6 );
    #endif
    roughnessFactor = clamp( roughnessFactor * ( 0.8 + 0.4 * verseBreak ), 0.04, 1.0 );
  }
#endif
`;

const DETAIL_COAT = /* glsl */ `
#if defined( VERSE_DECK_PLATES ) && defined( USE_CLEARCOAT )
  {
    // Broad, soft smudges dim the mirror a little and haze it a little. Only
    // large, rounded patches (a rotated domain, no lattice-aligned cells):
    // fine noise in the coat's roughness switched the probe's blur level from
    // one small cell to the next, which drew every light as blocky squares.
    vec2 q = mat2( 0.8, -0.6, 0.6, 0.8 ) * vVerseWorld.xz;
    float smudge = smoothstep( 0.35, 0.8, verseFbm( q * 0.45 ) );
    material.clearcoatRoughness = clamp( material.clearcoatRoughness + 0.025 * smudge + verseCoatBias, 0.02, 1.0 );
    material.clearcoat *= ( 1.0 - verseJoint ) * mix( 1.0, 0.85, smudge );
  }
#endif
`;

const BAKED = /* glsl */ `
#ifdef USE_LIGHTMAP
  totalEmissiveRadiance += verseDecode( texture2D( lightMap, vLightMapUv ) ) * verseBakedGain;
#endif
`;

function replaceOnce(source: string, find: string, replacement: string): string {
  const at = source.indexOf(find);
  if (at < 0) throw new Error(`deck shader: "${find}" not found`);
  if (source.indexOf(find, at + find.length) >= 0) throw new Error(`deck shader: "${find}" found twice`);
  return source.slice(0, at) + replacement + source.slice(at + find.length);
}

/**
 * The physical material's shaders with the baked radiance, box-projected
 * reflections and the close-up detail. Works on the templates three hands
 * to onBeforeCompile (the `#include` lines still unexpanded). Pure.
 */
export function patchDeckShader(vertexShader: string, fragmentShader: string): { vertexShader: string; fragmentShader: string } {
  let vs = replaceOnce(vertexShader, "#include <common>", "#include <common>\nvarying vec3 vVerseWorld;\nuniform float verseDepthPush;");
  vs = replaceOnce(vs, "#include <project_vertex>", `#include <project_vertex>\nvVerseWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xyz;\n${DEPTH_PUSH}`);
  let fs = replaceOnce(fragmentShader, "#include <common>", `#include <common>\n${FRAGMENT_HEAD}`);
  const envPars = replaceOnce(
    ShaderChunk.envmap_physical_pars_fragment,
    "reflectVec = transformDirectionByInverseViewMatrix( reflectVec, viewMatrix );",
    "reflectVec = transformDirectionByInverseViewMatrix( reflectVec, viewMatrix );\n\t\t\treflectVec = verseBoxProject( reflectVec, roughness );",
  );
  fs = replaceOnce(fs, "#include <envmap_physical_pars_fragment>", envPars);
  fs = replaceOnce(fs, "#include <metalnessmap_fragment>", `#include <metalnessmap_fragment>\n${DETAIL_PROPERTIES}`);
  fs = replaceOnce(fs, "#include <lights_physical_fragment>", `#include <lights_physical_fragment>\n${DETAIL_COAT}`);
  fs = replaceOnce(fs, "#include <emissivemap_fragment>", `#include <emissivemap_fragment>\n${BAKED}`);
  fs = replaceOnce(fs, "#include <lights_fragment_maps>", LIGHTS_FRAGMENT_MAPS);
  return { vertexShader: vs, fragmentShader: fs };
}

/**
 * Values every deck material shares (one uniform object each), for the whole
 * view at once: the baked radiance's gain (1), a bias on the deck coat's
 * roughness (0). QA runs tune them through `window.__verseTune`.
 */
export const DECK_SHARED = {
  verseBakedGain: { value: 1 },
  verseCoatBias: { value: 0 },
};

export interface ProbeBinding {
  env: Texture;
  position: readonly [number, number, number];
  boxMin: readonly [number, number, number];
  boxMax: readonly [number, number, number];
}

export interface DeckMaterialInputs {
  name: string;
  params: RealtimeMaterial;
  /** The lightmap page (rgbm2, flipY false, glTF UVs). */
  page: Texture;
  range: number;
  probe: ProbeBinding | null;
  /** The material's place in the deck's depth order (`depthOrder`). */
  order?: number;
}

/** Physical when the material needs a clear coat, a specular level other than 4 % or transparency; standard otherwise. */
export function needsPhysical(p: RealtimeMaterial): boolean {
  return p.clearcoat > 0 || p.transparent || Math.abs(p.specular - 0.5) > 0.05;
}

export function makeDeckMaterial({ name, params, page, range, probe, order = 0 }: DeckMaterialInputs): MeshStandardMaterial {
  const physical = needsPhysical(params);
  const m = physical ? new MeshPhysicalMaterial() : new MeshStandardMaterial();
  m.name = name;
  m.color = params.metalness > 0 ? new Color(params.color[0], params.color[1], params.color[2]) : new Color(0, 0, 0);
  m.roughness = params.roughness;
  m.metalness = params.metalness;
  m.lightMap = page;
  m.lightMapIntensity = 0; // the patch decodes the page as radiance, never as irradiance
  // Cycles renders both sides of a face; builders leave open quads (star fields, decals) facing either way.
  m.side = DoubleSide;
  m.envMap = probe?.env ?? null;
  m.envMapIntensity = params.specular <= 0 ? 0 : 1;
  if (m instanceof MeshPhysicalMaterial) {
    m.clearcoat = params.clearcoat;
    m.clearcoatRoughness = params.clearcoatRoughness;
    m.specularIntensity = Math.max(0, Math.min(1, params.specular * 2));
  }
  if (params.transparent) {
    // Glass: its own reflection plus what lies behind it, dimmed by its tint.
    m.transparent = true;
    m.opacity = params.opacity;
    m.depthWrite = false;
    m.premultipliedAlpha = false;
    m.blending = CustomBlending;
    m.blendSrc = OneFactor;
    m.blendDst = OneMinusSrcAlphaFactor;
  }
  const uniforms = {
    ...DECK_SHARED,
    verseRange: { value: range },
    verseDepthPush: { value: params.transparent ? 0 : depthPush(order) },
    verseBoxOn: { value: probe ? 1 : 0 },
    verseBoxMin: { value: new Vector3(...(probe?.boxMin ?? [0, 0, 0])) },
    verseBoxMax: { value: new Vector3(...(probe?.boxMax ?? [0, 0, 0])) },
    verseProbePos: { value: new Vector3(...(probe?.position ?? [0, 0, 0])) },
  };
  const detailDefine = { deck_plates: "VERSE_DECK_PLATES", painted: "VERSE_PAINTED", metal: "VERSE_METAL" }[params.detail];
  if (detailDefine) m.defines = { ...(m.defines ?? {}), [detailDefine]: "" };
  m.onBeforeCompile = (shader: WebGLProgramParametersWithUniforms) => {
    Object.assign(shader.uniforms, uniforms);
    const patched = patchDeckShader(shader.vertexShader, shader.fragmentShader);
    shader.vertexShader = patched.vertexShader;
    shader.fragmentShader = patched.fragmentShader;
  };
  m.customProgramCacheKey = () => `verse-deck-${physical ? "p" : "s"}-${params.detail}`;
  return m;
}
