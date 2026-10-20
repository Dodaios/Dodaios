# Industrial props (reactor, engineering, hangar)

Kit pieces for decks 3 (engineering) and 4 (hangar). Importing
`kit.props.industrial` registers every piece with `lib.kit`; deck builders then
call `kit.place("SM_...", location, rot_z_deg, room=...)`.

```python
import kit.props.industrial as industrial
industrial.reactor.place_reactor((54.0, -22.0, 0.0), room="reactor")  # whole shaft
kit.place("SM_Hangar_Shuttle", (50.0, -20.0, 0.0), room="flight_deck")
```

## Frames

- Floor-standing pieces: centred on X, deck at Z = 0, -Y toward the camera.
- Wall-mounted pieces (junction box, tool rack, warning panel, wall machinery,
  racks): back on the wall plane at local Y = 0, body toward -Y (into the room).
- Blast door: like an architecture wall, face toward -Y, body toward +Y.
- Reactor pieces: shaft centre at the origin. The collar is a 31.2 m square
  (26 modules) that replaces the deck floor around the shaft: leave that square
  open in the floor.
- Sockets: screens face along +Z of the socket; stand, spawn and waypoint
  sockets have +Z up and the character faces local -Y (as `lib.scene.add_socket`).

## Materials

Pieces ask `_mats.m(role)` for a material. A role resolves to the shared kit
material when `lib.materials` has it and otherwise to a temporary local one
named `M_TMP_PropsInd_<Role>`. The reactor core, containment field, haze and
stencil paints are props-specific and live here until the library adopts them.

## Lookdev

`lookdev.py` renders every piece through the plate camera (orthographic, 60
degrees) at 96 px/m plus a 3x crop, and the reactor and hangar vignettes;
`contact_sheet.py` assembles the sheet. Output goes to the git-ignored
`art/verse/.cache/lookdev/props-industrial/`.

## Pieces

| Piece | Size (m) | Nav | Sockets | Notes |
|---|---|---|---|---|
| SM_Reactor_Collar | 31.2 x 31.2 x 1.3 | walk | - | deck plate with the shaft hole, kerb lamps, rim plates, markings |
| SM_Reactor_Shaft | 28.4 x 28.4 x 64 | block | - | shaft wall: 32 ribs, girder rings, varied bays, ring pipes, 4 big lit rings, 88 flood spot lights |
| SM_Reactor_Core | 8.4 x 8.4 x 67.3 | block | - | hot core column, containment bands, vaned aperture head |
| SM_Reactor_ControlRing | 13 x 13 x 1.4 | walk | screen/stand ring_1..4 | ring r 5-6.5, tread plates, kerb lamps, 4 consoles, struts |
| SM_Reactor_Catwalk | 1.2 x 6.7 x 0.47 | walk | waypoint start/end | 1.2 m catwalk without railings, edge lamps |
| SM_Reactor_Haze | 29.6 x 29.6 x 64 | none | - | volume, density rising with depth |
| SM_Eng_PowerConduit | 1.2 x 1.2 x 6 | block | - | segmented floor-to-ceiling conduit, glowing inspection slots |
| SM_Eng_PowerConduit_Triple | 2.4 x 1.2 x 6 | block | - | three-tube conduit cluster |
| SM_Eng_JunctionBox | 1.2 x 0.35 x 2.1 | block | - | wall box, doors, indicators, conduits up the wall |
| SM_Eng_JunctionCabinet | 1.2 x 0.6 x 2.12 | block | - | floor cabinet |
| SM_Eng_CableTray_Floor | 2.4 x 0.64 x 0.26 | block | - | ladder tray with cables |
| SM_Eng_CableTray_Wall | 2.4 x 0.72 x 2.75 | none | - | bracketed wall tray at 2.6 m |
| SM_Eng_CoolantPipes | 4.8 x 1.3 x 1.0 | block | - | three pipes, flanges, valve, insulation |
| SM_Eng_WarningPanel | 1.2 x 0.12 x 3.05 | none | - | hazard-bordered panel, red beacon |
| SM_Eng_ToolRack | 2.48 x 0.45 x 2.3 | block | - | pegboard, tools, cases, gas cylinders |
| SM_Eng_DroneDock | 1.5 x 1.7 x 1.6 | block | spawn drone | charging pad and mast |
| SM_Eng_WallMachinery_A | 5.2 x 1.6 x 7.2 | block | - | hull-wall bay: transformer + pump |
| SM_Eng_WallMachinery_B | 5.2 x 1.6 x 7.2 | block | - | hull-wall bay: tank pair + ladder |
| SM_Hangar_Shuttle | 11 x 24.7 x 9.2 | block | spawn arrival, waypoint ramp_top, light cabin | original faceted shuttle, gull wings folded, ramp down, lit cabin |
| SM_Hangar_Container_L_Charcoal/Olive/Grey | 6.0 x 2.4 x 2.6 | block | - | corrugated containers with stencils |
| SM_Hangar_Container_M_Gunmetal/Charcoal | 3.6 x 2.4 x 2.4 | block | - |  |
| SM_Hangar_Container_S_Grey/Charcoal | 2.4 x 1.6 x 1.6 | block | - |  |
| SM_Hangar_Crate_A / _B | 1.2 x 0.8 x 0.8 / 0.8 x 0.6 x 0.5 | block | - | ribbed armoured crates |
| SM_Hangar_CrateStack | 2.4 x 0.84 x 2.1 | block | - |  |
| SM_Hangar_Pallet / _Loaded | 1.2 x 1.2 x 0.14 / 1.06 | block | - |  |
| SM_Hangar_FuelLine / _S | 6.0 x 0.6 / 2.6 x 0.15 | none | - | fuel + power hoses, coupling, cable ramp |
| SM_Hangar_FuelPort | 1.2 x 1.2 x 0.45 | block | - | floor hatch with coupling, valve, hose |
| SM_Hangar_TowTug | 3.7 x 1.96 x 1.68 | block | spawn drone | drone tow tug |
| SM_Hangar_GantryColumn | 1.6 x 3.2 x 13.05 | block | - | lattice column with rail bracket |
| SM_Hangar_GantryBridge | 25.2 x 3.2 x 13.7 | none | - | bridge girder, trolley, hook block |
| SM_Hangar_BlastDoor | 40.8 x 1.6 x 18.4 | block | - | two leaves in a pressure frame, lamps, BAY 4 stencils |
| SM_Hangar_LaunchWell | 32.4 x 14.4 x 10 | block (rim walk) | - | 30 x 12 m opening, lit walls, faint blue field, void |
| SM_Hangar_Marking_Pad / LaneDashed / LaneSolid / Chevrons / Hatch / BayNumber | decals | none | - | worn deck paint |
| SM_Eng_WallMachinery_A_12 / _B_12 | 5.2 x 1.6 x 12.0 | block | - | full-height hull bay: base machinery + service gantry at 7.4 m, heat exchangers, risers |
| SM_Eng_PowerConduit_480 | 1.2 x 1.2 x 4.8 | block | - | conduit for 4.8 m ceilings |
| SM_Eng_ValveCluster | 1.2 x 0.9 x 1.56 | block | - | three risers, header, valve wheels, gauges |
| SM_Eng_ChasePipes | 2.4 x 1.8 x 1.06 | block | - | service-chase pipe run under the 1.1 m cut |
| SM_Hangar_LandingPad | 14 x 14 x 0.04 | walk | - | plated pad, concentric seams, 12 recessed edge lights |
| SM_Hangar_FloorLight | 0.6 x 0.6 | none | - | round recessed up-light |
| SM_Hangar_PortalGantry | 17.2 x 3.6 x 11 | block legs, none bridge | - | portal crane, span 16, height 10, on rails |
| SM_Hangar_GantryRail | 0.36 x 12 | none | - | flush crane rail along local Y |
| SM_Hangar_FuelHydrant / FuelCart / ToolCart | 1.2 x 1.2 x 0.95 / 2.85 x 1.2 x 1.25 / 1.22 x 0.7 x 1.0 | block | - | fuel manifold, bowser, tool cart |
| SM_Hangar_BlastDoor_56 | 56 x 1.6 x 18.4 | block | - | 51.2 x 16 opening, continuous frame light band |
| SM_Hangar_ArmourRack | 2.5 x 0.68 x 2.3 | block | - | four generic armour sets |
| SM_Hangar_StorageRack | 4.9 x 1.2 x 4.6 | block | - | pallet racking with crates |

Helper: `hangar_service.build_hose(name, points, radius=0.075, room=None)` routes a floor hose
along any polyline (world metres; give z to rise into an intake).

Live table: `python scripts/verse/blender.py run --no-lock art/verse/kit/props/industrial/lookdev.py --list`.
