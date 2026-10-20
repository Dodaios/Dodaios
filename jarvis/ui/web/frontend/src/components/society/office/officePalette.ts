/**
 * The office's own colours: a contemporary workplace (docs/agent-society/office-map.md §2)
 * — light microcement floor, light-oak tops on black steel, graphite screens,
 * felt zone rugs, charcoal wayfinding with white type and lots of green.
 * Like the earlier worlds, nothing inside the canvas reads a theme token: the
 * scene is a lit diorama that looks the same in light and dark mode.
 */
export const OFFICE = {
  space: "#0d1320",
  slab: "#2a2e35",
  slabEdge: "#1c2027",
  /** Microcement floor: base plus the soft cloud tones and panel seams drawn over it. */
  floor: "#dcd8d1",
  floorCloud: ["#d4d0c8", "#e2ded8", "#d8d4cd", "#e6e3dd"],
  floorSeam: "rgba(120,114,104,0.22)",
  wood: "#d8bc94",
  woodDark: "#a88460",
  walkway: "#dcd8d1",
  deskTop: "#dcc39d",
  deskEdge: "#c9ab81",
  deskBody: "#f3f2ef",
  deskLeg: "#1f2226",
  steel: "#1f2226",
  chair: "#1d2025",
  chairSeat: "#3a3f47",
  chairMesh: "#40454e",
  monitor: "#16181c",
  monitorArm: "#b8bdc5",
  keyboard: "#e4e5e8",
  mug: "#f7f5f1",
  railing: "#23262b",
  glass: "#d6ecff",
  wallWhite: "#f6f5f2",
  signBoard: "#23262c",
  signText: "#ffffff",
  couch: "#bdb6aa",
  couchCushion: "#d8d1c4",
  couchAccent: ["#7f9a86", "#c98f6f", "#7c8fa8"],
  plantPot: "#34373d",
  planterLight: "#ebe6de",
  leaf: "#4f8f52",
  leafDark: "#2f6b3f",
  leafLight: "#77ad64",
  trunk: "#6b5440",
  book: ["#c8553d", "#e9b44c", "#4f7cac", "#5e9c76", "#8d6cab", "#e7e2d8"],
  rug: "#cfc7ba",
  ringWorking: "#4ade80",
  ringIdle: "#e8ecf2",
  ringWaiting: "#fbbf24",
  ringPaused: "#94a3b8",
} as const;

/**
 * Department zones: a felt rug, the matching acoustic wall panel and the seat
 * fabric of every chair in it — muted, contemporary tones that read on the
 * light floor without shouting.
 */
export const DEPARTMENT_ZONES = [
  { rug: "#bccab6", panel: "#8aa391", seat: "#6f8b77" },
  { rug: "#b9c6d4", panel: "#7b91ab", seat: "#5f7894" },
  { rug: "#ddd1bb", panel: "#bfa07a", seat: "#a8845a" },
  { rug: "#e2cbc0", panel: "#c48e7a", seat: "#b0705b" },
  { rug: "#c6c1d5", panel: "#918aad", seat: "#766e96" },
  { rug: "#b8d0c9", panel: "#6f9f94", seat: "#528579" },
  // The agents floor's campus holds up to twelve studios: mustard, rose, sky, olive, cocoa and indigo follow.
  { rug: "#e2d3a2", panel: "#c2a24c", seat: "#a8873a" },
  { rug: "#d8bfc7", panel: "#b0728a", seat: "#955a72" },
  { rug: "#b5cbd8", panel: "#5e93b0", seat: "#467a96" },
  { rug: "#cbcfa6", panel: "#92975a", seat: "#787d44" },
  { rug: "#d5c0b0", panel: "#a67a5e", seat: "#8b624a" },
  { rug: "#bbc2d5", panel: "#6d7aac", seat: "#566392" },
] as const;

/** Rug tints per department (kept for callers that only need the floor colour). */
export const DEPARTMENT_TINTS = DEPARTMENT_ZONES.map((z) => z.rug);

/**
 * The coding floor's own look: a tech campus floor. Polished pale concrete is
 * the ground, a terrazzo main street runs down the middle, and every team
 * neighbourhood is an island of white oak with long shared tables, a living
 * moss wall carrying its name, and phone booths in its colour along the
 * glass. The agents floor below keeps its wide oak planks and limestone.
 */
export const CODING_SCENE = {
  slabEdge: "#2b2a28",
  rim: "#ffe2bd",
  /** Daylight from a pale sky, a warm bounce off the oak. */
  sky: "#f6f4ef",
  ground: "#8a8076",
  /** Polished concrete: base, soft clouds of tone, and the saw-cut joints. */
  concrete: { base: "#d9d6d0", cloud: ["#d2cec7", "#e0ddd8", "#cfcbc4"], joint: "#b9b4ac" },
  /** The terrazzo main street, its chips, and the brass strip along its edges. */
  terrazzo: { base: "#ece7de", chips: ["#cfc5b5", "#b3a690", "#ddd2bf", "#93887a", "#c2a97e", "#7f8f86"] },
  /** White oak: the neighbourhoods' floor and the long tables. */
  oak: { seam: "#c4ad8c", planks: ["#e8dac2", "#e2d2b6", "#ecdfc9", "#ddcbad", "#efe4d0", "#e4d5bb"] },
  /** The living walls: moss tones, fern tones, and the white-oak frame. */
  moss: { base: "#4f6b3a", tones: ["#5d7b42", "#46613a", "#6e8a4b", "#3d5532", "#7a9655"], fern: "#86a85c", frame: "#d9c7a8" },
  /** The long tables' spine, legs and screens. */
  table: { top: "#e6d6ba", edge: "#cdb894", leg: "#2a2c30", spine: "#3a3d42", screen: "#eceae5" },
  brass: "#c9a24a",
  /** Linear pendants over the tables: body, lit underside and the pool of light below. */
  pendant: { body: "#f2f1ee", glow: "#fff1dc", pool: "#fff0d6" },
  /** The town square round the spawn terminal: the terrazzo medallion and its chips. */
  plaza: { terrazzo: "#efe9df", chips: ["#cbc0ae", "#a99b86", "#dccfb8", "#8d806d", "#b99f72"] },
  /** The desk's busy light: working, waiting for the person, failed, idle. */
  busy: { working: "#3ccf6e", waiting: "#ffb020", error: "#ff4d4d", idle: "#6b6f76" },
} as const;

/** A team neighbourhood's colour: the phone booths, chair seats and the stripe under its name. */
export interface TeamColours {
  /** The team's colour itself. */
  accent: string;
  /** A soft felt in that colour: booth interiors and seat fabric. */
  felt: string;
}

/**
 * One colour per neighbourhood, cycled by the department's tint index: clear,
 * friendly colours a company would paint its team areas in, each distinct
 * from the others and from the status colours of the busy lights.
 */
export const CODING_TEAMS: readonly TeamColours[] = [
  { accent: "#3f7fd9", felt: "#6f9ee0" },
  { accent: "#e36a4f", felt: "#e99079" },
  { accent: "#e2b33c", felt: "#e8c56c" },
  { accent: "#2f9e8f", felt: "#62b5a9" },
  { accent: "#8a63c9", felt: "#a68bd6" },
  { accent: "#d1557f", felt: "#dc7f9e" },
];

export function codingTeam(index: number): TeamColours {
  const n = CODING_TEAMS.length;
  return CODING_TEAMS[((index % n) + n) % n];
}

/** Colours of the room props (lobby, team room, wardrobe, break room). */
export const PROP_COLOURS = {
  steel: "#aab2bc",
  steelDark: "#6f7782",
  elevatorShaft: "#e7e4de",
  indicator: "#ffb347",
  lockers: ["#5fa8a0", "#e2856e", "#f2c14e", "#9b8ac4"],
  lockerVent: "#2f3440",
  mirror: "#d6ecf8",
  waterBottle: "#6fb7ea",
  waterTap: ["#e05a4f", "#4f8fe0"],
  mug: "#fdfbf7",
  coffee: "#5a3a24",
  espresso: "#c9ced4",
  chalkboard: "#2c3a33",
  arcadeBody: "#5b4a9e",
  arcadeTrim: "#2a2140",
  arcadeMarquee: "#ff7ab8",
  joystick: "#e0463c",
  arcadeButtons: ["#f2c14e", "#4fb3e0", "#6fd07a"],
  beanbag: ["#e27d60", "#85cdca", "#e8a87c", "#c38d9e", "#7d9bd6"],
  bell: "#e0b64a",
  boardFrame: "#d7d9dd",
  boardWhite: "#fbfbf8",
  /** The dark frame of the reception's help display (and the counter's brochure tray). */
  displayFrame: "#2a2e36",
  paper: "#fdfcf9",
  rugInner: "#c9b28f",
} as const;

/** Floor overlays per room kind: base colour plus the pattern's accent tones. */
export const ROOM_FLOOR_COLOURS = {
  lead: { base: "#6a432a", accents: ["#74492d", "#5e3a24", "#6c4429", "#7d5133", "#553420"] },
  // Contemporary rooms: slate felt (team), light terrazzo (wardrobe), large pale stone (reception),
  // light-oak planks (break room); on the coding floor a soft sage felt and a raised-floor grid.
  team: { base: "#b4bec6", accents: ["#aab4bd", "#bcc6cd", "#b0bac2"] },
  wardrobe: { base: "#ece8e2", accents: ["#c9c2b8", "#9aa4ad", "#d9b8aa", "#aebcaa"] },
  reception: { base: "#e9e6e1", accents: ["#ece9e4", "#e5e2dc", "#efece8"] },
  break: { base: "#d9c09b", accents: ["#dcc39f", "#d2b791", "#e0c8a6", "#cfb48c"] },
  // Mission Control: dark graphite microcement.
  command: { base: "#454b54", accents: ["#3e444c", "#4d535c", "#41474f", "#51575f"] },
  server: { base: "#c3c8cf", accents: ["#c9ced4", "#bcc2c9"] },
  // Arcade floor: the hall's midnight carpet, the game rooms' violet, teal and ember carpets, the foyer's terrazzo,
  // the prize shop's plum, the snack bar's checker red.
  arcade: { base: "#1a1430", accents: ["#211a3d", "#151027", "#2a1f4a"] },
  classics: { base: "#241446", accents: ["#2c1a55", "#1d1039"] },
  puzzle: { base: "#0f2a33", accents: ["#13343f", "#0b2129"] },
  action: { base: "#2e160c", accents: ["#3a1c0f", "#241008"] },
  foyer: { base: "#24202e", accents: ["#2c2838", "#1d1a26"] },
  prizes: { base: "#3a1838", accents: ["#431c41", "#33152f"] },
  snack: { base: "#5a1e22", accents: ["#e9e2d6", "#4c191c"] },
  // Level Hall: deep midnight-blue polished stone with gold veins.
  levels: { base: "#e7e0d0", accents: ["#e7e0d0", "#2b2d33", "#bdb3a0", "#b8964f"] },
} as const;

/**
 * The agents floor's rooms take their floors from the campus's own finishes instead: the plank oak of the open
 * floor (break room), the same oak a tone deeper and laid as a chevron (lead office), the limestone of the window
 * band (lobby, and as terrazzo with oak and stone chips in the wardrobe) and the slate felt of the focus booths
 * (team room). One floor family from the studios to the last room.
 */
export const CAMPUS_ROOM_FLOORS = {
  lead: { base: "#a98a64", accents: ["#b08f69", "#9f805b", "#a98964", "#b89872", "#967752"] },
  team: { base: "#c3cbd3", accents: ["#bac3cc", "#cbd2d9", "#bfc7cf"] },
  wardrobe: { base: "#e7e0d4", accents: ["#d3cabb", "#c9ad8c", "#b9b0a3", "#efe9df"] },
  reception: { base: "#e7e0d4", accents: ["#ddd5c7", "#efe9df", "#e2dace"] },
  break: { base: "#dcc6a1", accents: ["#e4d0ae", "#dcc6a1", "#e9d8ba", "#d8bf98"] },
} as const;

/** Checkpoint gold: floor ring, hexagon token and the label badge. */
export const CHECKPOINT_GOLD = { ring: "#f5b83d", rim: "#e0a02a", face: "#f7c65a", faceDeep: "#e39b1f", icon: "#ffffff" } as const;

/**
 * The lead office's executive suite, in the campus's own materials a tone
 * deeper: smoked oak, bronze, cognac leather and a slate rug. (The keys keep
 * the names the suite was built with: `walnut*` is its timber, `brass` its
 * metal.) Bronze is the one metallic accent beside the floor's dark steel, so
 * the boss's room reads as the most precious place on the floor without
 * leaving its family.
 */
export const LEAD_SUITE = {
  walnut: "#8b6b4a",
  walnutDark: "#6a4f37",
  walnutLight: "#ad8a63",
  brass: "#b08d5c",
  leather: "#8e5a3a",
  leatherDark: "#6b4129",
  leatherTan: "#b98558",
  velvetGold: "#c9a25a",
  chrome: "#c9ced6",
  blackGlass: "#12141a",
  marble: "#eeeae3",
  led: "#ffd08a",
  lampGlass: "#2f7a4f",
  shade: "#fff0d2",
  backlight: "#a07a52",
  glass: "#e8d3a8",
  rug: { field: "#39414d", inner: "#48515e", border: "#b08d5c", accent: "#8e5a3a" },
  globe: { ocean: "#5f8f96", land: "#e2cd98", line: "#3d5c61" },
  bottles: ["#b8661e", "#4f7a3a", "#d9e6ea", "#8c2a2a", "#c79a3a"],
  trophy: "#e8b949",
  dog: { basket: "#8b6b4a", cushion: "#8e5a3a" },
} as const;
