# Dodaios Bar

The Dodaios Bar is the default on-screen overlay (`[ui] orb_style =
"jarvis_bar"`): a small dark pill, centred near the bottom edge of the screen.
It shows whether a voice runs and who is speaking, and it holds the voice
controls under the pointer.

## Shapes

| Shape | When | What it shows |
|-------|------|---------------|
| rest | idle, nothing switched on | a small pill (about 40 x 8 pt on a 15-inch MacBook Air): a half-clear black fill in a light rim |
| status | idle with the microphone muted, the voice muted or Prompt Mode on | one mark per switch (slashed microphone, slashed speaker, sparkle) |
| live | a conversation (after the wake phrase, a shortcut or a click) or a dictation runs | a row of eleven short white bars; the status marks stay on the left |
| open | the pointer is on the bar | round controls line up (below); the control under the pointer shows a label above the bar in the interface language |

The pill eases between shapes (about 75 ms) and keeps its bottom centre, so it
grows upward and evenly to both sides. A notice (a refused request) shows a
blinking cross in the live pill and does not open.

## Place

The default place is centred, 12 pt above the bottom of the screen's work
area (above a visible Dock or taskbar). A drag moves the bar; the place is
saved in `[jarvisbar]` together with `placement = "pill"`. A place saved
without that marker belongs to an earlier bar of another size and is not
reused.

## The level bars

- The bars grow and shrink with the live audio level. While the person speaks, the
  microphone feeds them; while Dodaios speaks, its voice output feeds the
  same bars through the same level feed (`ui/orb/bus_bridge.py`,
  `_note_tts_level` and `_on_mic_level`; Dodaios's voice wins while it plays).
- Silence draws a still row of dots: nothing moves when nothing is heard.
- Thinking (and a dictation being transcribed): a soft light walks across the
  dots.
- Connecting a realtime call: a small wave runs along the row; when the call
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
