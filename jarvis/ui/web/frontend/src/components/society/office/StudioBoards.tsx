/**
 * The live face of every studio board: team name, members with their real
 * run state, the newest lines of the team's chat (studioBoardContent.ts).
 *
 * A face is a canvas texture, created the first time the camera comes close
 * and redrawn only when what it shows changed. Only the few boards nearest
 * the camera count as live: they are the ones whose transcript is refreshed
 * (useTeamRounds reads `boardWatch`). The faces take no pointer events; the
 * board's station does.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useFrame } from "@react-three/fiber";
import { CanvasTexture, SRGBColorSpace } from "three";
import { useT } from "@/i18n";
import type { SocietyAgent } from "../data";
import { studioBoardFace, type OfficeLayout, type Studio } from "./officeLayout";
import { studiosOf } from "./officeTeams";
import { BOARD_CANVAS, BOARD_LIFT_M, boardModel, boardSignature, drawStudioBoard, pickBoards, type BoardLabels } from "./studioBoardContent";
import { boardWatch, useTeamwork } from "./teamwork";

const CHECK_EVERY_S = 0.4;

function useBoardLabels(): BoardLabels {
  const t = useT();
  return useMemo(() => ({
    pool: t("society.office.studio_pool"),
    members: t("society.office.team_members"),
    live: t("society.office.team_live"),
    speaking: t("society.office.board_speaking"),
    you: t("society.office.you"),
    empty: t("society.office.board_empty"),
    poolNote: t("society.office.board_pool_note"),
    loading: t("society.office.board_loading"),
    unavailable: t("society.office.board_unavailable"),
    lead: t("society.office.team_lead"),
    more: t("society.office.board_more"),
    state: {
      working: t("society.office.state_working"), waiting: t("society.office.state_waiting"),
      idle: t("society.office.state_idle"), paused: t("society.office.state_paused"),
    },
  }), [t]);
}

function BoardFace({ studio, agents, labels, active }: {
  studio: Studio; agents: ReadonlyMap<string, SocietyAgent>; labels: BoardLabels; active: boolean;
}) {
  const board = studio.board;
  const round = useTeamwork((s) => (studio.teamId ? s.rounds[studio.teamId] : undefined));
  // The canvas exists from the first time the camera came close; a board never seen costs nothing.
  const [seen, setSeen] = useState(active);
  useEffect(() => { if (active) setSeen(true); }, [active]);
  const surface = useMemo(() => {
    if (!seen || typeof document === "undefined") return null;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    canvas.width = BOARD_CANVAS.w; canvas.height = BOARD_CANVAS.h;
    const texture = new CanvasTexture(canvas);
    texture.colorSpace = SRGBColorSpace;
    texture.anisotropy = 4;
    return { ctx, texture };
  }, [seen]);
  useEffect(() => () => surface?.texture.dispose(), [surface]);
  const model = useMemo(() => boardModel(studio, agents, round, labels), [studio, agents, round, labels]);
  const signature = boardSignature(model, labels);
  const drawnSignature = useRef("");
  useEffect(() => {
    // A board out of sight keeps its last face; it catches up when the camera returns.
    if (!surface || !active || drawnSignature.current === signature) return;
    drawnSignature.current = signature;
    drawStudioBoard(surface.ctx, model, labels);
    surface.texture.needsUpdate = true;
    // `signature` covers the model and the labels.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [surface, active, signature]);
  if (!board || !surface) return null;
  // The same sheet the board shows at rest, a hair in front of it and lit the same way, so the writing simply appears on it.
  const face = studioBoardFace(board);
  const nx = Math.sin(face.rotationY), nz = Math.cos(face.rotationY);
  return (
    <mesh position={[face.position[0] + nx * BOARD_LIFT_M, face.position[1], face.position[2] + nz * BOARD_LIFT_M]}
      rotation={[0, face.rotationY, 0]} raycast={() => null} userData={{ studioBoard: board.id }}>
      <planeGeometry args={face.size} />
      <meshStandardMaterial map={surface.texture} roughness={0.9} emissive="#ffffff" emissiveMap={surface.texture} emissiveIntensity={0.18} />
    </mesh>
  );
}

export function StudioBoards({ layout, agents, awake }: { layout: OfficeLayout; agents: ReadonlyMap<string, SocietyAgent>; awake: boolean }) {
  const labels = useBoardLabels();
  // This floor's own entry among the watched boards; another floor awake at the same time has its own.
  const stage = useMemo(() => Symbol("studio-boards"), []);
  const studios = useMemo(() => studiosOf(layout).filter((s) => s.board !== null), [layout]);
  const [drawn, setDrawn] = useState<ReadonlySet<string>>(new Set());
  const nextCheck = useRef(0);
  useFrame(({ camera, clock }) => {
    if (clock.elapsedTime < nextCheck.current) return;
    nextCheck.current = clock.elapsedTime + CHECK_EVERY_S;
    const picked = pickBoards(studios.map((s) => ({
      id: s.board!.id, teamId: s.teamId,
      distance: Math.hypot(camera.position.x - s.board!.x, camera.position.y - 1.2, camera.position.z - s.board!.z),
    })));
    boardWatch.set(stage, picked.live);
    if (picked.drawn.size !== drawn.size || [...picked.drawn].some((id) => !drawn.has(id))) setDrawn(picked.drawn);
  });
  // Asleep or gone, this floor watches no board; what another floor watches is its own business.
  useEffect(() => {
    if (!awake) boardWatch.clear(stage);
    return () => boardWatch.clear(stage);
  }, [awake, stage]);
  if (studios.length === 0) return null;
  return (
    <group>
      {studios.map((studio) => (
        <BoardFace key={studio.board!.id} studio={studio} agents={agents} labels={labels} active={drawn.has(studio.board!.id)} />
      ))}
    </group>
  );
}
