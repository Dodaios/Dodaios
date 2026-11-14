# Dodaios Bar

The Dodaios Bar is the default on-screen overlay (`[ui] orb_style =
"jarvis_bar"`): a small black pill with white marks near the bottom edge of
the screen. It shows whether a voice runs and who is speaking, and it holds
the voice controls under the pointer.

## Shapes

| Shape | When | What it shows |
|-------|------|---------------|
| rest | idle, nothing switched on | a slim pill, no marks |
| status | idle with the microphone muted, the voice muted or Prompt Mode on | one mark per switch (slashed microphone, slashed speaker, sparkle) |
| live | a conversation (after the wake phrase, a shortcut or a click) or a dictation runs | eleven level bars; the status marks stay on the left |
| open | the pointer is on the bar | the controls (below) slide out around the centre |

The pill eases between shapes (about 75 ms) and stays anchored at its bottom
centre. A notice (a refused request) shows a blinking cross in the live pill
and does not open.

## The level bars

- The bars move with the live audio level. While the person speaks, the
  microphone feeds them; while Dodaios speaks, its voice output feeds the
  same bars through the same level feed (`ui/orb/bus_bridge.py`,
  `_note_tts_level` and `_on_mic_level`; Dodaios's voice wins while it plays).
- Silence draws a still row of dots: nothing moves when nothing is heard.
- Thinking (and a dictation being transcribed): a soft light walks across the
  dots.
- Connecting a realtime call: a small wave runs left to right; when the call
  is connected, one swell runs from the middle to both ends.

## Controls (open bar)

| Mode | Controls, left to right |
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

Right-click opens the main window, a middle click or double click puts the bar
back at its default place, and a drag moves it (the place is saved in
`[jarvisbar]`).

## Code

- `dodaios/ui/dodaiosbar/design.py`: layout, hit test and drawing (Pillow
  only). Both surfaces and the tests use it.
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
