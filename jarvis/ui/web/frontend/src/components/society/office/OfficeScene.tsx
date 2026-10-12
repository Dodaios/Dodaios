/**
 * The office floors: an oak-floored plate floating in a starry night behind
 * frameless glass, walled rooms in the north and south and the desks in
 * between — and everybody in it. The agents floor is a team campus (a studio
 * per team round an atrium, boulevards, planted courts), the coding floor has
 * a department per IDE workspace; each dresses its plan in its own look
 * (AgentsFloorLook / CodingFloorLook). The Level Hall's floor wears the
 * agents floor's materials. The arcade floor has a plan and a look of its own
 * (ArcadeHall); the person, the elevator and the camera work the same there.
 */
import { useLayoutEffect, useMemo } from "react";
import { Stars } from "@react-three/drei";
import type { ThreeEvent } from "@react-three/fiber";
import { Color } from "three";
import { useT } from "@/i18n";
import type { SocietyAgent } from "../data";
import type { ToyLook } from "./toyFigureModel";
import { DeskInstances } from "./DeskInstances";
import { DeskDressing } from "./DeskDressing";
import { CodingSlab, CodingStudio } from "./CodingFloorLook";
import { CodingFloorAmbience } from "./CodingFloorAmbience";
import { AGENTS_SCENE, AgentsDepartment, AgentsSlab } from "./AgentsFloorLook";
import { AgentsFloorAmbience } from "./AgentsFloorAmbience";
import { CampusGround } from "./CampusGround";
import { StaticBatch } from "./StaticBatch";
import { BuildingShell } from "./BuildingShell";
import { ExecutiveDesks, LeadOfficeLight } from "./LeadSuite";
import { LiveMonitors } from "./LiveMonitors";
import { TerminalMonitors } from "./TerminalMonitors";
import type { PaneOccupant } from "./codingFloor";
import { GigiFlyer } from "./GigiFlyer";
import { useEventStore } from "@/store/events";
import type { DeskChat } from "./useDeskChats";
import { FurniturePiece, MeetingChairs } from "./OfficeProps";
import { TeamBoardFace } from "./TeamBoardFace";
import { TeamRoomFittings } from "./TeamRoomDecor";
import { BreakLoungeFittings } from "./BreakLounge";
import { WardrobeFittings } from "./WardrobeRoom";
import { LevelHallFittings } from "./LevelHall";
import { LobbyFittings } from "./LobbyDecor";
import { SpawnFittings } from "./SpawnPoint";
import { RoomFloors, RoomSign, RoomWalls } from "./OfficeRooms";
import { StationObjects } from "./StationObjects";
import { ElevatorCallButton } from "./ElevatorCallButton";
import { ArcadeHall } from "../arcade/ArcadeHall";
import { OFFICE_FIGURE_HEIGHT_M, OfficeAgents, type WalkerContext } from "./OfficeAgents";
import { OfficePlayer } from "./OfficePlayer";
import { OfficeDog } from "./OfficeDog";
import { PlayerBubble } from "./OfficeBubbles";
import { OfficeCameraRig } from "./OfficeCameraRig";
import { allDesks, type FurnitureKind, type OfficeLayout, type Point } from "./officeLayout";
import { isWalkable, nearestWalkable, type NavGrid } from "./officeNav";
import { CODING_SCENE, OFFICE } from "./officePalette";
import { officeSession, player as playerBody, useOfficeStore, type OfficeFloor, type Selection } from "./officeStore";
import { arrivalPose } from "./officeFloors";
import { ProgressionLayer } from "../progression/ProgressionLayer";

/** The person's character as a mover for Gigi to follow (the body object itself, mutated every frame). */
const PLAYER_OWNER = { current: playerBody };

/**
 * Places the character on a floor it just arrived at (elevator ride, or a
 * mount that asked for another floor). Runs as a layout effect, so it lands
 * before the player controller checks its spot; it repeats for every rebuilt
 * plan until the floor's roster has loaded, then the arrival is done.
 */
function FloorArrival({ floor, layout, grid, ready, awake }: { floor: OfficeFloor; layout: OfficeLayout; grid: NavGrid; ready: boolean; awake: boolean }) {
  useLayoutEffect(() => {
    if (!awake) return;
    const arrival = officeSession.arrival;
    if (!arrival || arrival.floor !== floor) return;
    const pose = arrivalPose(layout, arrival.at, officeSession.floors[floor]);
    const spot = isWalkable(grid, pose) ? pose : nearestWalkable(grid, pose) ?? layout.spawn;
    playerBody.x = spot.x; playerBody.z = spot.z; playerBody.heading = pose.heading;
    playerBody.path = []; playerBody.moving = false;
    officeSession.playerPlaced = true;
    if (ready) officeSession.arrival = null;
  }, [floor, layout, grid, ready, awake]);
  return null;
}

/** On the coding floor Jarvis is nobody's desk mate: the person's pet (Gigi by default) comes along. */
function GigiCompanion({ grid, awake, reduced }: { grid: NavGrid; awake: boolean; reduced: boolean }) {
  const speaking = useEventStore((s) => s.voiceState === "speaking");
  const clear = useMemo(() => (x: number, z: number) => isWalkable(grid, { x, z }), [grid]);
  return <GigiFlyer owner={PLAYER_OWNER} mode="follow" speaking={speaking} paused={!awake} reduced={reduced} clear={clear} />;
}

export interface OfficeSceneProps {
  floor: OfficeFloor;
  /** The coding floor's figures by agent id (their IDE panes); empty on the agents floor. */
  occupants: ReadonlyMap<string, PaneOccupant>;
  /** The floor's roster has loaded (ends a pending arrival). */
  ready: boolean;
  layout: OfficeLayout;
  grid: NavGrid;
  walkers: WalkerContext;
  agents: ReadonlyMap<string, SocietyAgent>;
  newcomers: ReadonlySet<string>;
  awake: boolean;
  reduced: boolean;
  overview: number;
  player: { look: ToyLook; name: string };
  selection: Selection | null;
  nearby: Selection | null;
  chats: ReadonlyMap<string, DeskChat>;
  onOpenScreen: (agentId: string, screen: Point & { y: number }, facing: number) => void;
  /** The elevator's call button: lit after a press, the floor picker open (its pill steps aside), and the press itself. */
  elevatorCall: { lit: boolean; picking: boolean; onPress: () => void };
}

/** The stations, the elevator's call button and the person: the same on every floor. */
function SharedFloorParts({ floor, layout, grid, ready, awake, reduced, player, selection, nearby, elevatorCall }: Pick<OfficeSceneProps,
  "floor" | "layout" | "grid" | "ready" | "awake" | "reduced" | "player" | "selection" | "nearby" | "elevatorCall">) {
  const shaft = layout.furniture.find((f) => f.kind === "elevator");
  const atLift = nearby?.kind === "checkpoint" && nearby.id === "elevator";
  return (
    <>
      {/* Stations are the objects of the room: a click target and a rim on each, nothing floating over the floor. */}
      <StationObjects layout={layout} nearby={nearby} selection={selection} animate={awake && !reduced} />
      {shaft && (
        <ElevatorCallButton shaft={shaft} floor={floor} lit={elevatorCall.lit} animate={awake && !reduced}
          near={atLift} onPress={elevatorCall.onPress} />
      )}
      <FloorArrival floor={floor} layout={layout} grid={grid} ready={ready} awake={awake} />
      <OfficePlayer layout={layout} grid={grid} look={player.look} name={player.name} awake={awake} reduced={reduced} />
      <PlayerBubble height={OFFICE_FIGURE_HEIGHT_M + 0.49} />
    </>
  );
}

export function OfficeScene(props: OfficeSceneProps) {
  const { floor, layout, grid, walkers, agents, newcomers, awake, reduced, selection, nearby, chats, overview } = props;
  const arcade = floor === "arcade";
  const select = useOfficeStore((s) => s.select);
  const desks = useMemo(() => allDesks(layout), [layout]);
  const dogBeds = useMemo(() => layout.furniture.filter((f) => f.kind === "dogBed"), [layout]);
  const treatJar = layout.furniture.find((f) => f.kind === "treatJar") ?? null;
  const onFloorClick = (event: ThreeEvent<MouseEvent>) => {
    // A drag that ends on the floor rotated the camera; only a real click walks.
    if (event.delta > 6) return;
    event.stopPropagation();
    useOfficeStore.getState().requestWalk({ x: event.point.x, z: event.point.z });
  };
  // One tree for every floor (the dressing swaps, the person and the camera stay mounted), in the order the frame loop needs:
  // the floor, the person, then whoever walks around them, the camera last.
  return (
    <>
      {arcade
        // While a cabinet is being played its screen in the hall rests: the live preview would only draw behind the overlay.
        ? <ArcadeHall layout={layout} onFloorClick={onFloorClick} awake={awake} reduced={reduced}
          nearCabinet={nearby?.kind === "arcade" && selection?.kind !== "arcade" ? nearby.id : null} />
        : <OfficeFloorDressing {...props} desks={desks} onFloorClick={onFloorClick} />}
      <SharedFloorParts {...props} />
      {dogBeds.length > 0 && <OfficeDog beds={dogBeds} rooms={layout.rooms} jar={treatJar} grid={grid} awake={awake} reduced={reduced} />}
      {!arcade && (
        <OfficeAgents desks={desks} agents={agents} ctx={walkers} newcomers={newcomers} awake={awake} reduced={reduced} chats={chats}
          selectedId={selection?.kind === "agent" ? selection.id : null} onSelect={(id) => select({ kind: "agent", id })} />
      )}
      {/* Upstairs the person's pet comes along: to the coding floor and to play in the arcade. */}
      {floor !== "agents" && <GigiCompanion grid={grid} awake={awake} reduced={reduced} />}
      {/* Levels: what everyone wears, level-up bursts and "+XP"; after the walkers, so it reads this frame's positions. */}
      <ProgressionLayer awake={awake} reduced={reduced} />
      <OfficeCameraRig layout={layout} overview={overview} />
    </>
  );
}

/**
 * The props a station lights up when the person is near, and the spawn point's pad: each stays an object of its
 * own (the rim is drawn on the meshes under its group) and is merged only within itself. Every other piece of
 * the agents floor is drawn merged with all the others (StaticBatch).
 */
const STATION_PROP_KINDS: ReadonlySet<FurnitureKind> = new Set<FurnitureKind>([
  "spawnTerminal", "spawnPad", "receptionDesk", "agentTotem", "teamBoard", "dressingMirror", "mirror", "coffeeBar", "elevator", "studioBoard", "teamStand",
]);

/** Everything that dresses the agents and coding floors: slab, rooms, departments, desks, monitors, furniture. */
function OfficeFloorDressing({ floor, occupants, layout, agents, newcomers, awake, reduced, chats, onOpenScreen, desks, onFloorClick }: OfficeSceneProps & {
  desks: ReturnType<typeof allDesks>;
  onFloorClick: (event: ThreeEvent<MouseEvent>) => void;
}) {
  const t = useT();
  // Lead desks carry their own size and are built as executive desks, not bench instances.
  const benchDesks = useMemo(() => desks.filter((d) => !d.size), [desks]);
  // Each desk takes its department's zone colour for the felt screen and the seat fabric.
  const zones = useMemo(() => new Map(layout.departments.flatMap((dept) => dept.desks.map((desk) => [desk.id, dept.tint] as const))), [layout]);
  const leadRoom = layout.rooms.find((r) => r.kind === "lead");
  const teamRoom = layout.rooms.find((r) => r.kind === "team");
  const breakRoom = layout.rooms.find((r) => r.kind === "break");
  const coding = floor === "coding";
  // The coding floor floats in a violet night of its own, so a glance tells the floors apart.
  const space = coding ? CODING_SCENE.space : OFFICE.space;
  const background = useMemo(() => new Color(space), [space]);
  const { minX, maxX, minZ, maxZ } = layout.bounds;
  const span = Math.max(maxX - minX, maxZ - minZ);
  const shadowMap = span > 50 ? 4096 : 2048;
  const table = layout.furniture.find((f) => f.kind === "meetingTable");
  const board = layout.furniture.find((f) => f.kind === "teamBoard");
  const wardrobeRug = layout.furniture.find((f) => f.kind === "roundRug" && f.room === "wardrobe");
  const lobbyLamp = layout.furniture.find((f) => f.kind === "lobbyLamp");
  const spawnTerminal = layout.furniture.find((f) => f.kind === "spawnTerminal");
  const levelStage = layout.furniture.find((f) => f.kind === "studioStage");
  const levelGuide = layout.furniture.find((f) => f.kind === "levelGuide") ?? null;
  // The agents floor's furniture, room signs, studio walls and meeting chairs never change once built: they are
  // merged by material, a few dozen draw calls instead of well over a thousand (and as many again for shadows).
  const batch = floor === "agents";
  const roomLabels = layout.rooms.map((room) => t(`society.office.room_${room.kind}`));
  const signs = layout.rooms.map((room, i) => <RoomSign key={room.id} room={room} label={roomLabels[i]} />);
  const batchKey = useMemo(() => [
    layout.furniture.map((f) => `${f.id}@${f.x},${f.z},${f.rotationY}`).join(";"),
    layout.departments.map((d) => `${d.id}:${d.label}:${d.tint}@${d.minX},${d.minZ},${d.maxX},${d.maxZ}`).join(";"),
    roomLabels.join(";"), t("society.office.studio_pool"), t("society.office.studio_sign_team"), t("society.office.studio_sign_pool"),
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ].join("|"), [layout, roomLabels.join(";"), t]);
  return (
    <>
      <primitive attach="background" object={background} />
      <fog attach="fog" args={[space, span * 2.2, span * 4.5]} />
      <Stars radius={span * 3} depth={span} count={2500} factor={4} saturation={0} fade speed={reduced ? 0 : 0.3} />
      <hemisphereLight args={coding ? [CODING_SCENE.sky, CODING_SCENE.ground, 0.95] : [AGENTS_SCENE.sky, AGENTS_SCENE.ground, 0.95]} />
      <ambientLight intensity={0.25} />
      {/* The campus is twice as long as the other floors: its sun keeps the same shadow detail with a larger map. */}
      <directionalLight key={shadowMap} position={[maxX + 10, 26, maxZ + 6]} intensity={1.55} color="#fff7ec" castShadow
        shadow-mapSize={[shadowMap, shadowMap]} shadow-bias={-0.0004} shadow-normalBias={0.03}
        shadow-camera-left={-span * 0.7} shadow-camera-right={span * 0.7}
        shadow-camera-top={span * 0.7} shadow-camera-bottom={-span * 0.7} shadow-camera-far={Math.max(120, span * 2 + 40)} />
      {coding ? <CodingSlab layout={layout} onFloorClick={onFloorClick} /> : <AgentsSlab layout={layout} onFloorClick={onFloorClick} />}
      {coding ? <CodingFloorAmbience layout={layout} /> : <AgentsFloorAmbience layout={layout} />}
      {/* The agents floor and the Level Hall are floors of a building: window walls, the tower below, the city outside. */}
      {!coding && <BuildingShell layout={layout} />}
      <RoomFloors rooms={layout.rooms} campus={!coding} />
      <RoomWalls walls={layout.walls} />
      {!batch && signs}
      {coding
        ? <>
          {layout.departments.map((dept) => <CodingStudio key={dept.id} dept={dept} agents={agents} />)}
          <DeskDressing desks={benchDesks} departments={layout.departments} />
        </>
        : <>
          {/* The campus ground (boulevards, atrium, free plot, planted courts); the Level Hall's floor has none. */}
          <CampusGround layout={layout} />
          {benchDesks.length > 0 && <>
            <DeskInstances desks={benchDesks} agents={agents} zones={zones} />
            <DeskDressing desks={benchDesks} departments={layout.departments} floor="agents" />
          </>}
        </>}
      <ExecutiveDesks desks={desks} agents={agents} onOpenScreen={onOpenScreen} />
      {leadRoom && <LeadOfficeLight room={leadRoom} />}
      {floor === "coding"
        ? <TerminalMonitors desks={desks} occupants={occupants} awake={awake} onOpen={onOpenScreen} />
        : <LiveMonitors desks={desks} agents={agents} chats={chats} onOpen={onOpenScreen} />}
      {batch
        ? <>
          <StaticBatch signature={batchKey}>
            {signs}
            {layout.departments.map((dept) => <AgentsDepartment key={dept.id} dept={dept} />)}
            {layout.furniture.filter((item) => !STATION_PROP_KINDS.has(item.kind)).map((item) => <FurniturePiece key={item.id} item={item} />)}
            {table && <MeetingChairs table={table} />}
          </StaticBatch>
          {layout.furniture.filter((item) => STATION_PROP_KINDS.has(item.kind)).map((item) => <FurniturePiece key={item.id} item={item} merged />)}
        </>
        : <>
          {layout.furniture.map((item) => <FurniturePiece key={item.id} item={item} />)}
          {table && <MeetingChairs table={table} />}
        </>}
      {board && <TeamBoardFace board={board} enabled={awake && floor === "agents"} />}
      {teamRoom && table && <TeamRoomFittings room={teamRoom} table={table} />}
      {breakRoom && <BreakLoungeFittings room={breakRoom} furniture={layout.furniture} />}
      {wardrobeRug && <WardrobeFittings rug={wardrobeRug} />}
      {levelStage && <LevelHallFittings stage={levelStage} guide={levelGuide} />}
      {lobbyLamp && <LobbyFittings lamp={lobbyLamp} />}
      {spawnTerminal && <SpawnFittings terminal={spawnTerminal} arrival={layout.arrival} floor={floor} newcomers={newcomers} animate={awake && !reduced} />}
    </>
  );
}
