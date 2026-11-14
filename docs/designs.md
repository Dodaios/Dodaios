# Designs

A design changes how the whole app looks: its colours and, if the person
wants, a background that moves. A person makes one by telling Dodaios how the
app should look ("dark blue with a soft glow drifting in the background").
Dodaios picks the colours, saves the design and switches it on.

**Settings > Designs** lists every design:

- a field to describe a new design; the sentence goes into the lead
  conversation as the person's own message;
- **Standard** (the app's own look) and the person's own designs, each one
  click to switch, with rename and delete;
- the designs Dodaios ships as examples (Deep Sea, Ember, Forest, Night Sky,
  Dusk, Paper);
- **Back to standard** in the header, which switches designs off. The designs
  stay in the list.

A design follows the Appearance setting (dark, light, system). It can set
colours for the dark appearance, the light one, or both; an appearance it
leaves out keeps the standard colours.

## A design

| Field | Rule |
|-------|------|
| `id` | made from the name (`"Deep Sea"` -> `deep-sea`); `standard` is reserved |
| `name` | 1 to 40 characters |
| `description` | up to 300 characters, what the person asked for |
| `dark`, `light` | colours for that appearance, or `null`; at least one is set |
| `background` | `style`, `colors`, `speed`, `strength` |

Each appearance needs `background`, `foreground` and `accent` as `#rrggbb`.
These keys are optional: `sidebar`, `card`, `popover`, `surface`, `border`,
`muted`, `primary`, `user_bubble`, `bubble_out`, `bubble_in`, `success`,
`warning`, `destructive`.

The app derives every other colour (`src/lib/designs/tokens.ts`): the surface
ladder goes up from the room on dark and down on light, the secondary inks are
mixed from the foreground toward the room, and every fill gets white or
near-black ink, whichever reads better.

The background:

| Field | Values |
|-------|--------|
| `style` | `none`, `glow` (soft drifting light), `waves` (bands of light), `stars` (twinkling points), `gradient` (a slowly turning colour gradient) |
| `colors` | 1 to 5 `#rrggbb` (none for `none`) |
| `speed` | `slow`, `medium`, `fast` |
| `strength` | 0 to 1, default 0.5 |

The app's surfaces are opaque, so the background lies over the window,
ignores the pointer and blends into it: `screen` on dark (white text stays
white), `multiply` on light (dark text stays dark). The colours are tuned for
the blend: deep on dark, soft on light. Every motion is a transform on a few
large layers. With reduced motion the background stands still.

## Where designs live

`<DATA_DIR>/designs.json` holds the person's own designs and the active id:

```json
{"version": 1, "active": "midnight", "designs": [{"id": "midnight", "...": "..."}]}
```

Built-in designs are in `dodaios/ui/designs/presets.py` and are not written to
the file. Each app instance has its own data directory, so the Dev app never
changes the person's app. A broken entry is skipped and logged; an active id
that no longer exists reads as `standard`.

The frontend keeps a copy of the active design's stylesheet in localStorage
(`jarvis.design`). The boot script in `index.html` puts it on the page before
the first paint, so the standard colours never flash at launch.

## API

| Method | Path | What it does |
|--------|------|--------------|
| GET | `/api/designs` | every design (built-in first), `active`, and the allowed keys and styles |
| POST | `/api/designs` | make a design; with `id`, change one of the person's own (fields left out keep their value) |
| PUT | `/api/designs/active` | switch to a design; `{"id": "standard"}` is the standard look |
| POST | `/api/designs/reset` | back to the standard look |
| DELETE | `/api/designs/{design_id}` | delete one of the person's own designs |

`POST /api/designs` switches to the design unless `apply` is `false`. Built-in
designs cannot be changed or deleted; saving a changed copy without an `id`
makes the person's own. Every change publishes `UiDesignChanged` (`active`),
and every open window reloads the designs.

The same actions are the commands `design-list`, `design-save`,
`design-apply`, `design-reset` and `design-delete` (`docs/commands-reference.md`),
so Dodaios reaches them as tools. `design-delete` asks first.
