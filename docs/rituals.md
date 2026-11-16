# Rituals

A ritual is a sequence the owner wrote beforehand and starts by saying a short phrase after the
wake word, or by typing it: "Good morning", and the music starts, the news and the open pull
requests are there. What takes time is gathered ahead and kept back until the phrase is said,
so nobody waits for the research.

## How it differs from what already exists

| | What starts it | What it is |
| --- | --- | --- |
| Routine ([routines.md](routines.md)) | the clock, or an event | a fixed prompt whose result is posted when it is done |
| Standing task ([standing-tasks.md](standing-tasks.md)) | the assistant, at its own pace | an open-ended responsibility |
| Skill with a voice trigger | a spoken pattern | instructions for the next model turn; nothing runs by itself |
| **Ritual** | its phrase, spoken or typed | steps for that moment, and steps gathered ahead and handed over then |

Use a routine for "every day at 8 send me X". Use a ritual for "when I say X, do this and have
that ready".

## What a ritual holds

- `name`, and up to five `phrases` that start it, without the wake word, at most six words each.
- Optional conditions: a time window (`window_from`, `window_to`, may run over midnight),
  `weekdays` (Monday is 0), and `once_per_day` (default): the phrase starts it only the first
  time on a day. Outside these the phrase is an ordinary greeting.
- A ritual's day is the day its window opens on. With a window over midnight (22:00 to 02:00),
  00:30 still belongs to the evening before: `once_per_day` holds for the whole evening, and
  `weekdays` name the evening the window opened on.
- `steps`, each a sentence in the owner's own words:
  - `now`: happens the moment the phrase is said. It may ask for anything the assistant can do.
  - `ahead`: gathered before that moment and kept back until then.
- `prepare_from`: from when the `ahead` steps are gathered; default is the start of the window.
  It is a time inside the window or at most 12 hours before it opens; any other time is refused.
  A gathering before the window is for the window that opens next (from 23:00 for a 06:00
  window gathers for the next morning).
- At most 20 rituals, 12 steps each.

## When a phrase starts a ritual

No model reads the sentence. The phrase has to carry it: after the wake word, the assistant's
name and courtesy words are peeled off both ends, what is left must be the phrase, word for
word (said once or more). "Good morning, how is the weather" is a question and starts nothing.
Words are compared without case, accents and punctuation; an apostrophe inside a word is no
break ("What's" is "Whats"), and an umlaut matches its two-letter spelling and its plain vowel
(an o-umlaut matches "oe" and "o", a sharp s matches "ss").

When a sentence names more than one ritual, one that may start now wins over one its
conditions hold back, then the one whose phrase is the longer part of the sentence.

The phrase starts its ritual only inside its conditions. A click on "Run now" or a start the
assistant makes on request (`ritual-run`) always runs, and does not use up the phrase's one
start of the day.

- Spoken (classic voice path): the hook sits in `SpeechPipeline._handle_utterance_turn` after
  fragments were joined and before the privacy phrases, the skills and the brain.
- Typed: only in the assistant's own conversation and only as a bare sentence. The message is
  filed, the card is the answer, no turn is started.

## What a start does

1. The phrase is filed into the conversation and a card says the ritual started. It carries
   what was gathered ahead, when that is ready.
2. `now` steps:
   - A step that is exactly one tool call may carry that call (`call`: the tool, its arguments,
     and the call in plain words). The assistant works it out once, when it writes the ritual
     on request. At the start the call is made directly, with no model. It goes through the
     same gate as every tool call, on the surface where nobody can be asked: a call that would
     need a question, fails, or names a tool that is gone leaves its step to a turn. A call that
     gives no answer within 20 seconds is not repeated by a turn, because it may have happened.
     A call is checked against the app's tools when it is written; a switch or a rename later
     keeps it as it is, even when its tool is gone for now.
   - Every other step runs in one turn of the assistant's conversation, with the owner's
     standing and nothing typed. When the conversation stays busy for ten minutes, a second
     card names the steps that did not run.
3. By voice, what was gathered is said in its short form. With nothing gathered yet the voice
   says one line; what arrives later is said when the call is still open.

## Gathering ahead

The `ahead` steps are worked through by a quiet lead routine, one per ritual, tagged
`lead-ritual:<id>`. Its trigger never fires by itself and no routine list shows it.

- **When.** A clock reads the wall time every 15 seconds and starts the run when the day is
  allowed, the time is inside the gathering window (`prepare_from` to the end of the window),
  the phrase has not started the ritual today, and no good result is there. The moment is not
  a fixed time on purpose: a laptop that is closed at the named time gathers when it is
  opened. The clock waits while macOS is only briefly awake in the background.
- **Fresh.** A result is gathered anew when it is four hours old, when a start took it, or when
  the `ahead` steps changed. A failed day is tried once more after ten minutes.
- **Only looking.** The run's chat is in the `ask` mode and every approval card is refused, like
  a standing task on the `watch` level. What the run reads on the web cannot make it change
  anything. It has no shell; for pull requests it uses
  `GET /api/agentic-ide/git/github/pull-requests`.
- **Kept back.** The answer has two parts, one made for the ear and one written. Both are
  stored on the ritual's row of the day (`rituals.db`, table `ritual_days`). Nothing reaches
  the conversation before the ritual starts.
- **A start that came first.** If nothing is ready (the machine slept, the phrase came early),
  the card says so, the gathering starts at once, and its result follows in a second card. A
  failure is tried once more, then said. A run that cannot even begin (no scheduler, the
  routine cannot be set up) is said at once. When the `ahead` steps were changed while the run
  gathered, it gathers again for the steps as they are now.
- **One run.** Two starts in the same moment (a click and the clock) start one run.

## Who may write one

- The owner, in the assistant's panel (Library tab), or by asking the assistant.
- The assistant has `ritual-list`, `ritual-create`, `ritual-update`, `ritual-remove` and
  `ritual-run`. Through the raw routes it asks first.
- Out of a run nobody watches (a routine's own chat) a ritual can only be written switched
  off, and none can be changed, removed or started: its steps later run with the owner's
  standing.

## API

`/api/agent-chat/lead/rituals`: `GET` (all, with where each stands today), `POST`,
`GET /match?text=` (would this sentence start one now; starts nothing), `GET|PATCH|DELETE /{id}`
(id or exact name), `POST /{id}/run`, `POST /{id}/prepare`.

## Where the code is

- `dodaios/rituals/models.py`, `store.py`: the ritual and its day.
- `matcher.py`: is this sentence the phrase.
- `service.py`: writing one, the conditions, the start.
- `prepare.py`: gathering ahead, the clock, the routine runner's hooks.
- `instant.py`: a step that is one tool call.
- `said.py`: the spoken and the typed way in.
- `dodaios/ui/web/ritual_routes.py`, `dodaios/commands/registry.py` (`ritual-*`).
