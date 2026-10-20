# Art study brief: the city in the singularity

## Intent

The world outside the agents floor and the Level Hall: the Dodaios tower
stands in a megacity at night, built round a singularity. Seen from the
floor it should read as a high-end game world: depth and vertigo, a city
that lives (windows, traffic, light), and one unmistakable landmark.

## Viewing conditions

- The camera orbits the floor and always looks down (polar 20° to 72°);
  at its flattest the horizon just shows. Normal distances: 2.5 m (walking)
  to about 140 m (overview). The city is composed to be seen from above:
  roofs, avenues and traffic lanes read at every zoom.
- The floor itself stays the subject: nothing outside rises into it or
  stands between it and the camera (plaza, roof limit, lane headroom, all
  enforced by `cityPlan.test.ts`).

## Direction

- Shape language: glass towers of four classes (block, setback, tapering
  prism, spire) on a 36 m street grid, avenues every second line; a crater
  round the singularity ringed by gold-crowned spires.
- Palette: deep indigo night and violet haze; windows cool white, warm
  amber and a little cyan; gold as the one accent (seams, crowns, the
  singularity's rings), matching the brand's charcoal and gold.
- Light: everything outside is self-lit by its own shaders (the scene's sun
  never reaches it); exponential aerial perspective into the sky's colour;
  mist over the street level.
- Motion: lit offices switch now and then, pulses climb the light seams,
  street and flying traffic move, the accretion disc turns, the orbital
  rings rotate. With reduced motion the clock stands still.

## Production approach

The city is procedural runtime geometry and shaders (instanced towers,
GPU-animated traffic), not authored meshes, because it is a distant
backdrop of hundreds of objects whose look is light, not form. There is
therefore no Blender source or GLB export in this study; the runtime
components are `SingularityCity.tsx`, `cityShaders.ts` and `cityPlan.ts`
under `dodaios/ui/web/frontend/src/components/society/office/`.

## Budgets

About twenty draw calls for the whole city, nothing in the shadow pass,
no per-frame CPU work beyond one clock and three rotations.
