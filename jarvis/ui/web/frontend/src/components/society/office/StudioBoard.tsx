/**
 * The studio board: every team studio's own wall screen, standing in front of
 * its name wall. A slim graphite panel on two steel legs with an oak ledge
 * and a warm light bar on top. Its face is a calm paper-white sheet with a
 * dot grid; whatever the team is doing is drawn over it by the layer that
 * owns the live content, placed with `studioBoardFace` from the layout.
 *
 * Everything stays inside the `studioBoard` footprint, which navigation walks
 * round. All boards share their materials.
 *
 * The team stand belongs to the same family: the lectern on the free plot
 * where a new team is started. A steel post on a foot carries a slanted oak
 * panel with a pale sheet, a plus drawn on it and the board's light bar along
 * its upper edge. It carries no text; the layer that owns the interaction
 * labels it.
 */
import { MeshStandardMaterial } from "three";
import { cachedCanvasTexture } from "./canvasMaterials";
import { Box, matte } from "./OfficeFurniture";
import { FURNITURE_SIZE, STUDIO_BOARD_FACE } from "./officeLayout";

const SIZE = FURNITURE_SIZE.studioBoard;
/** The panel behind the face: a bezel round it, and thin enough to leave the face proud of nothing but itself. */
const PANEL = { w: SIZE.w, h: STUDIO_BOARD_FACE.h + 0.18, d: 0.1 } as const;
/** The resting face is the board's face plane; live content is drawn a few millimetres in front of it. */
const REST_FACE_Z = STUDIO_BOARD_FACE.z;

const BOARD_MAT = {
  panel: matte("#2a2d33", { roughness: 0.55 }),
  leg: matte("#1f2226", { roughness: 0.4, metalness: 0.5 }),
  ledge: matte("#d9bf97", { roughness: 0.6 }),
  light: new MeshStandardMaterial({ color: "#fff0d8", emissive: "#fff0d8", emissiveIntensity: 1.3, toneMapped: false }),
};

let restFace: MeshStandardMaterial | null = null;
/** Paper-white with a fine dot grid, lit a little from within so it reads as a screen at rest. */
function restFaceMaterial(): MeshStandardMaterial {
  if (!restFace) {
    const map = cachedCanvasTexture("studio-board:rest", 432, 232, (ctx, w, h) => {
      ctx.fillStyle = "#f6f3ec";
      ctx.fillRect(0, 0, w, h);
      ctx.fillStyle = "rgba(60,56,50,0.16)";
      for (let y = 12; y < h; y += 20) for (let x = 12; x < w; x += 20) ctx.fillRect(x, y, 2, 2);
    });
    restFace = new MeshStandardMaterial({
      color: map ? "#ffffff" : "#f6f3ec", map, roughness: 0.9,
      ...(map ? { emissive: "#ffffff", emissiveMap: map, emissiveIntensity: 0.18 } : {}),
    });
  }
  return restFace;
}

/** One studio board, in its own frame: origin on the floor under its centre, face towards +z. */
function StudioBoard() {
  const panelY = STUDIO_BOARD_FACE.y;
  const panelBottom = panelY - PANEL.h / 2;
  return (
    <group>
      {[-SIZE.w / 2 + 0.22, SIZE.w / 2 - 0.22].map((x) => (
        <Box key={x} size={[0.05, panelBottom, 0.05]} position={[x, panelBottom / 2, -0.02]} material={BOARD_MAT.leg} />
      ))}
      <Box size={[PANEL.w, PANEL.h, PANEL.d]} position={[0, panelY, 0]} material={BOARD_MAT.panel} />
      <mesh position={[0, panelY, REST_FACE_Z]} material={restFaceMaterial()}>
        <planeGeometry args={[STUDIO_BOARD_FACE.w, STUDIO_BOARD_FACE.h]} />
      </mesh>
      {/* The ledge for pens, and the light bar washing the face from above. */}
      <Box size={[1.5, 0.03, 0.075]} position={[0, panelBottom - 0.015, 0.035]} material={BOARD_MAT.ledge} cast={false} />
      <Box size={[PANEL.w - 0.16, 0.025, 0.05]} position={[0, panelY + PANEL.h / 2 + 0.0125, 0.045]} material={BOARD_MAT.light} cast={false} />
    </group>
  );
}

/** The slanted panel of the team stand: its size, its slope from the horizontal and its middle's height. */
const STAND = { w: 0.74, d: 0.42, t: 0.03, slope: 0.6, y: 1.04 } as const;
const STAND_MAT = {
  sheet: matte("#f6f3ec", { roughness: 0.9 }),
  ink: matte("#2b2926", { roughness: 0.8 }),
};

/** The team stand, in its own frame: origin on the floor under its middle, its face towards +z and up. */
function TeamStand() {
  return (
    <group>
      <Box size={[0.46, 0.03, 0.4]} position={[0, 0.015, 0]} material={BOARD_MAT.leg} cast={false} />
      <Box size={[0.06, STAND.y - 0.03, 0.06]} position={[0, (STAND.y + 0.03) / 2, -0.03]} material={BOARD_MAT.leg} />
      <group position={[0, STAND.y, 0]} rotation={[STAND.slope, 0, 0]}>
        <Box size={[STAND.w, STAND.t, STAND.d]} position={[0, 0, 0]} material={BOARD_MAT.ledge} />
        <Box size={[STAND.w - 0.1, 0.006, STAND.d - 0.1]} position={[0, STAND.t / 2 + 0.003, 0.01]} material={STAND_MAT.sheet} cast={false} />
        {/* The plus: start something here. */}
        <Box size={[0.2, 0.006, 0.045]} position={[0, STAND.t / 2 + 0.008, 0.01]} material={STAND_MAT.ink} cast={false} />
        <Box size={[0.045, 0.006, 0.2]} position={[0, STAND.t / 2 + 0.008, 0.01]} material={STAND_MAT.ink} cast={false} />
        <Box size={[STAND.w - 0.06, 0.018, 0.022]} position={[0, STAND.t / 2 + 0.009, -STAND.d / 2 + 0.02]} material={BOARD_MAT.light} cast={false} />
      </group>
    </group>
  );
}

export const STUDIO_RENDERERS = {
  studioBoard: () => <StudioBoard />,
  teamStand: () => <TeamStand />,
};
