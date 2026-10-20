/**
 * Lighting the live people like the photograph lights the room they stand in.
 *
 * Reflections come from the deck's environment map (scene.environment, PMREM).
 * Diffuse light comes from the cooked light probe of the room the actor is in:
 * each actor material carries its own nine SH coefficients and the shader uses
 * them in place of the environment's diffuse term, so a crew member walking
 * from the cold bridge into the warm mess picks up the mess's light. The
 * coefficients ease over half a second when the actor changes room. The same
 * room light also grazes the body's edges as a soft rim, so dark uniforms
 * keep their silhouette against dark decks at the close camera.
 */
import { Vector3, type Material, type MeshStandardMaterial } from "three";
import type { Deck, LightProbe } from "../content/deck";

const PATCH_KEY = "verse-room-probe";

const ROOM_IRRADIANCE = "shGetIrradianceAt( inverseTransformDirection( geometryNormal, viewMatrix ), verseRoomSH )";
/** How much of the room's light grazes a body's edges as rim light (GLSL float literal). */
const ROOM_RIM_GAIN = "0.16";

/**
 * The standard material's fragment template with the room probe as its
 * diffuse light. The template still holds `#include` lines at this point
 * (three expands them later), so the patch goes after the includes: once the
 * environment map's diffuse term is in `iblIrradiance`, it is replaced by the
 * room's; without an environment map the room's light is added directly.
 * Pure.
 */
export function patchRoomLight(fragmentShader: string): string {
  return fragmentShader
    .replace("#include <lights_pars_begin>", ["#include <lights_pars_begin>", "uniform vec3 verseRoomSH[ 9 ];"].join("\n"))
    .replace(
      "#include <lights_fragment_maps>",
      [
        "#include <lights_fragment_maps>",
        "#if defined( RE_IndirectDiffuse ) && defined( USE_ENVMAP ) && defined( ENVMAP_TYPE_CUBE_UV )",
        `iblIrradiance = ${ROOM_IRRADIANCE} * envMapIntensity;`,
        "#elif defined( RE_IndirectDiffuse )",
        `irradiance += ${ROOM_IRRADIANCE};`,
        "#endif",
      ].join("\n"),
    )
    .replace(
      "#include <lights_fragment_end>",
      [
        "#include <lights_fragment_end>",
        // Rim: the room's own light grazing the body's edges, so a dark uniform keeps its silhouette on a dark deck
        // at the close third-person camera (a game's character rim, kept low enough to stay photographic).
        "{",
        "  float verseRim = pow( 1.0 - saturate( dot( geometryNormal, geometryViewDir ) ), 4.0 );",
        `  reflectedLight.indirectSpecular += verseRim * ( ${ROOM_RIM_GAIN} * ${ROOM_IRRADIANCE} + vec3( 0.006, 0.0065, 0.008 ) );`,
        "}",
      ].join("\n"),
    );
}

export class RoomLight {
  /** The uniform shared by all of one actor's materials. */
  readonly sh = { value: Array.from({ length: 9 }, () => new Vector3()) };
  private readonly target = Array.from({ length: 9 }, () => new Vector3());
  private probe: LightProbe | null = null;
  private primed = false;

  /** Patch an actor's materials to read this light. */
  attach(materials: Iterable<Material>): void {
    for (const m of materials) {
      const std = m as MeshStandardMaterial;
      if (!std.isMeshStandardMaterial) continue;
      std.onBeforeCompile = (shader) => {
        shader.uniforms.verseRoomSH = this.sh;
        shader.fragmentShader = patchRoomLight(shader.fragmentShader);
      };
      std.customProgramCacheKey = () => PATCH_KEY;
      std.needsUpdate = true;
    }
  }

  /** Follow the probe of the room at (x, y, z); `immediate` skips the easing. */
  update(deck: Deck, x: number, y: number, z: number, dtS: number, immediate = false): void {
    const probe = probeAt(deck, x, y, z);
    if (probe !== this.probe) {
      this.probe = probe;
      for (let i = 0; i < 9; i++) {
        const c = probe?.sh[i] ?? [0, 0, 0];
        this.target[i].set(c[0], c[1], c[2]);
      }
    }
    // The first reading is taken as is: a body must not fade in from black.
    const k = immediate || !this.primed ? 1 : 1 - Math.pow(0.5, dtS / 0.25);
    this.primed = true;
    for (let i = 0; i < 9; i++) this.sh.value[i].lerp(this.target[i], k);
  }
}

export function insidePolygon(x: number, z: number, polygon: readonly (readonly [number, number])[]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, zi] = polygon[i];
    const [xj, zj] = polygon[j];
    if (zi > z !== zj > z && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) inside = !inside;
  }
  return inside;
}

/** The probe of the room the point stands in; outside every room, the nearest probe. Pure. */
export function probeAt(deck: Pick<Deck, "rooms" | "probes">, x: number, y: number, z: number): LightProbe | null {
  const room = deck.rooms.find((r) => Math.abs(r.floorY - y) < 1 && insidePolygon(x, z, r.polygon));
  const own = room ? deck.probes.find((p) => p.room === room.id) : undefined;
  if (own) return own;
  let best: LightProbe | null = null;
  let bestD = Infinity;
  for (const p of deck.probes) {
    const d = Math.hypot(p.x - x, p.z - z);
    if (d < bestD) { bestD = d; best = p; }
  }
  return best;
}
