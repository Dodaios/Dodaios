# Starship Verse — brief

Status: in production (2026-10-19). Replaces the office tower (team campus,
coding floor, arcade, Level Hall) as the Dodaios Verse.

## Intent

The maintainer asked for the whole Verse to be rebuilt from scratch as a
starship in the spirit of the big space-opera franchises: a ship on which
you see the agents walk the decks and do their work. Every creative decision
below the "it is a starship" line was delegated.

The ship is called **Dodaios**. The person is its captain. The agents are its
crew: androids, because they are AI. The person's pet (Jarvis) is the ship's
companion and follows the captain.

## References studied

- Enterprise-D main bridge (fan reconstruction renders, Tadeo D'Oria): a
  sunken command area with three seats inside a curved tactical rail, two
  forward consoles facing the viewscreen, aft stations along the wall,
  back-lit ceiling coffers, warm carpets. Takeaway: a calm, readable room
  organised round one centre; light comes from the architecture itself.
- Normandy SR-2 (Mass Effect wiki): five decks with one job each (cabin,
  command with a galaxy map in the centre, crew deck with mess and
  observation lounges, engineering round a vertical drive core, hangar).
  Takeaway: a deck is a place with a purpose; the holographic map in the
  middle of the command deck is the heart people gather round.
- Star Wars (Rebel corvette corridors, Star Destroyer crew pits): ribbed
  white corridors, recessed crew pits below the walkway, hard-surface
  greebles. Takeaway: crews work below and around a raised walkway; ribs and
  frames give rhythm.

No franchise asset, logo, insignia, typeface or interface design (such as
LCARS or the delta) is copied. The ranks are the generic naval ladder.

## Shape language

Long horizontal lines with rounded corners and chamfered frames. Rooms are
rounded rectangles or circles; corridors carry structural ribs every 2.4 m.
Consoles are wedge desks with a sloped glass top. Nothing is boxy-flat: every
wall panel has an inset seam and a light line.

## Colour hierarchy

1. Charcoal deck plating and graphite structure (the brand's charcoal).
2. Warm white ceramic wall panels.
3. Gold for command and for anything the person uses (brand gold).
4. Cyan for information (holograms, screens).
5. State colours only on real state: green working, amber waiting, grey idle.

## Materials and light

PBR: brushed metal with an environment map, ceramic panels rough 0.55,
glass with fresnel. Light comes from emissive strips, ceiling coffers and
screens, made to glow by a bloom pass; one soft overhead key light gives
contact shadows. Outside: a star field, a nebula and the destination's
planet, all self-lit.

## Camera and viewing distance

Cut-away deck seen from above at 40–70°, orbiting and following the captain;
figures read at 15 m, the deck plan at 60–120 m. Walls stand 2.6 m with a lit
top edge so the cut reads as intentional.

## Budgets

Target: 60 fps at 2560 × 1440 on the development RTX 5070 Ti with 40 agents,
and a usable 30 fps on an integrated GPU with the low quality setting (no
bloom, no shadows, DPR 1). Draw calls under 600 on the largest deck.

## Decks

| Deck | Replaces | Purpose |
|---|---|---|
| Bridge | lead office | captain's chair, the lead as first officer, helm (destinations), viewscreen |
| Operations | agents floor | divisions (one per team) round holo-tables, transporter (new agents), mess and observation lounge, rest pods, quartermaster |
| Engineering | coding floor | reactor core, one bay per IDE workspace, live terminals |
| Holodeck | arcade | the retro games as holographic cabinets |
| Hall of Honour | Level Hall | the rank wall and the service record |

## Unresolved

- Hangar and shuttle flight in space (the courier) are not part of the first
  pass.
