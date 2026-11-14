# Dodaios Bar

The Dodaios Bar is the default on-screen overlay (`[ui] orb_style =
"jarvis_bar"`): a slim upright black pill with white marks at the left edge of
the screen, centred in its height. It shows whether a voice runs and who is
speaking, and it holds the voice controls under the pointer.

## Shapes

| Shape | When | What it shows |
|-------|------|---------------|
| rest | idle, nothing switched on | a thin dark pill (slightly see-through), no marks |
| status | idle with the microphone muted, the voice muted or Prompt Mode on | one mark per switch, stacked (slashed microphone, slashed speaker, sparkle) |
| live | a conversation (after the wake phrase, a shortcut or a click) or a dictation runs | a stack of eleven short white lines; the status marks stay on top |
| open | the pointer is on the bar | round controls stack up (below); the control under the pointer shows a label beside the bar in the interface language |

The pill eases between shapes (about 75 ms); it keeps its left edge and its
middle, so it grows to the right and evenly up and down. A notice (a refused
request) shows a blinking cross in the live pill and does not open.

## Place

The default place is the left edge of the screen's work area, centred in its
height. A drag moves the bar; the place is saved in `[jarvisbar]` together
with `placement = "side"`. A place saved without that marker belongs to the
earlier bottom-centred bar and is not reused.

## The level lines

- The lines grow and shrink with the live audio level. While the person speaks, the
  microphone feeds them; while Dodaios speaks, its voice output feeds the
  same lines through the same level feed (`ui/orb/bus_bridge.py`,
  `_note_tts_level` and `_on_mic_level`; Dodaios's voice wins while it plays).
- Silence draws a still stack of dots: nothing moves when nothing is heard.
- Thinking (and a dictation being transcribed): a soft light walks across the
  dots.
- Connecting a realtime call: a small wave runs down the stack; when the call
  is connected, one swell runs from the middle to both ends.

## Controls (open bar)

| Mode | Controls, top to bottom |
|------|-------------------------|
| idle | sparkle (only with Prompt Mode on), microphone, centre, speaker, pencil |
| conversation | microphone, centre, speaker, X |
| dictation | centre, X |

| Control | Click |
|---------|-------|
| microphone | mute or unmute the microphone (`VoiceMuteToggleRequested`) |
| speaker | mute or unmute Dodaios's voice for this session |
| centre (idle) | start a conversation |
| centre (conversation) | nothing, so a stray click never ends a call |
| X | hang up; while dictating, stop the dictation |
| pencil | open the window on a new typed chat (`ComposeRequested`) |
| sparkle | pause or resume Prompt Mode |

Right-click opens the main window, and a middle click or double click puts the
bar back at its default place.

## Code

- `dodaios/ui/dodaiosbar/design.py`: layout, hit test, labels and drawing
  (Pillow only). Both surfaces and the tests use it. The labels come from
  `dodaios/i18n/locales/*.json` (`ui.bar.*`); the bridge sends the interface
  language to the surface (`set_language`, also over the companion host's
  protocol).
- `dodaios/ui/dodaiosbar/renderer.py`: screen-scale calibration and "Bar size",
  the mode-to-look rule (`visual_mode`), and the two frame formats: a true
  RGBA frame at the screen's pixel density for the macOS Qt surface
  (`render_rgba`), and an RGB frame on a colour key for the Tk surface
  (`render`; half-covered edge pixels keep the dark pill colour, so no key
  fringe appears).
- `dodaios/ui/dodaiosbar/interaction.py::resolve_click`: control to action.
- Surfaces: `qt_overlay.py` (macOS, in the companion host), `overlay.py`
  (Windows and Linux).
- Guards: `tests/unit/ui/dodaiosbar/test_bar_design.py` and the other files in
  that folder.
