/**
 * The cut-away: walls that would hide what the camera looks at sink to a
 * kerb, like an architect's model with its near walls lifted off. The hull
 * drops on every side the camera is outside of; an inner wall drops while it
 * stands between the camera and the captain. It happens in the vertex shader
 * of the shared finishes, from two attributes every merged part carries
 * (`cutAB`: the wall's line, `cutKind`: 0 never, 1 hull, 2 inner), so the
 * merged geometry stays merged.
 */
import type { Material } from "three";

export const CUTAWAY = {
  uCutCam: { value: [0, 0] as [number, number] },
  uCutFocus: { value: [0, 0] as [number, number] },
  /** 1 = on. */
  uCutOn: { value: 1 },
  /** 1 = inner walls too (off in the overview, where nothing stands in front). */
  uCutInner: { value: 1 },
};

const DECL = /* glsl */ `
attribute vec4 cutAB;
attribute float cutKind;
uniform vec2 uCutCam;
uniform vec2 uCutFocus;
uniform float uCutOn;
uniform float uCutInner;
uniform float uCutKeep;
uniform float uCutDrop;
varying float vShipCut;
bool shipCut() {
  if (cutKind < 0.5 || uCutOn < 0.5) return false;
  vec2 a = cutAB.xy, b = cutAB.zw;
  if (cutKind < 1.5) {
    vec2 d = b - a;
    // The hull runs clockwise from the bow, so (d.y, -d.x) points outwards.
    return dot(uCutCam - a, vec2(d.y, -d.x)) > 0.0;
  }
  if (uCutInner < 0.5) return false;
  vec2 r = uCutCam - uCutFocus, s = b - a;
  float den = r.x * s.y - r.y * s.x;
  if (abs(den) < 1e-5) return false;
  vec2 qp = a - uCutFocus;
  float t = (qp.x * s.y - qp.y * s.x) / den;
  float u = (qp.x * r.y - qp.y * r.x) / den;
  return t > 0.0 && t < 1.0 && u > -0.04 && u < 1.04;
}
`;

const patched = new WeakSet<Material>();

/**
 * Teach a shared finish the cut-away. Idempotent. A cut part keeps `keep` of
 * its height and sinks by `drop` (glass sinks out of sight instead of
 * squashing into a bright band).
 */
export function withCutaway<M extends Material>(material: M, keep = 0.14, drop = 0): M {
  if (patched.has(material)) return material;
  patched.add(material);
  const previous = material.onBeforeCompile;
  material.onBeforeCompile = (shader, renderer) => {
    previous?.call(material, shader, renderer);
    Object.assign(shader.uniforms, CUTAWAY, { uCutKeep: { value: keep }, uCutDrop: { value: drop } });
    shader.vertexShader = DECL + shader.vertexShader.replace(
      "#include <begin_vertex>",
      "#include <begin_vertex>\n  vShipCut = 0.0;\n  if (shipCut()) { transformed.y = transformed.y * uCutKeep - uCutDrop; vShipCut = 1.0; }",
    );
    // A cut wall reads as a dark kerb, not as a pale slab: its colour (and its lights) dim.
    shader.fragmentShader = "varying float vShipCut;\n" + shader.fragmentShader.replace(
      "#include <color_fragment>",
      "#include <color_fragment>\n  diffuseColor.rgb *= mix(1.0, 0.32, vShipCut);",
    );
  };
  material.customProgramCacheKey = () => "ship-cutaway";
  return material;
}
