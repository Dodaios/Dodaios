// The cuts of the Nodes clip and the Assistant clip of the README.
// nodes-plugins-cut.cjs turns a cut into the video.
//
// The rules are the ones of the clip at the top of the README (edit-agents.js):
// the take in its own order, nothing laid over it. A wait for a model is left
// out (the picture before it dissolves into the one after it) and the typing
// plays at an even pace. Everything else plays at the speed it was filmed at.
// A clip has a longest length (`max`); what its shots are longer is taken off
// all of them alike by the cutter, which refuses more than a quarter.
//
// Footage is named by the stretches clip-nodes.cjs and clip-assistant.cjs film.

// Seconds a typed key in the video. The take types about as fast; the cut
// only makes the pace even, whatever the computer was busy with meanwhile.
const KEY = 0.036;

function builder(footage) {
  const shots = [];
  const leftOut = [];
  const len = (name) => footage.length(name);
  // `stretch` from its second `from` to its second `to`, played in `seconds`.
  const play = (stretch, from, to, seconds, o = {}) => {
    if (!footage.has(stretch) || seconds <= 0.001) return;
    shots.push({ stretch, seconds, src: o.src || [{ t: 0, v: Math.max(0, from) }, { t: seconds, v: to }], dissolve: Boolean(o.dissolve), typing: Boolean(o.typing), what: o.what || '' });
  };
  // Footage at the speed it was filmed at.
  const part = (stretch, from, to, o) => {
    const a = Math.max(0, from), b = Math.min(len(stretch), to);
    play(stretch, a, b, b - a, o);
  };
  const whole = (stretch, o) => part(stretch, 0, len(stretch), o);
  const start = (stretch, seconds, o) => part(stretch, 0, seconds, o);
  const end = (stretch, seconds, o) => part(stretch, len(stretch) - seconds, len(stretch), o);
  // A text typed in `stretch`: the way to the field, the typing at an even
  // pace, and what follows the last key (the text is read, then sent).
  const typing = (stretch, name, { lead = 1.0, o } = {}) => {
    const keys = footage.keys(name, stretch);
    if (!keys.length) { whole(stretch, o); return; }
    part(stretch, keys[0] - lead, keys[0], { ...o, what: 'to the field' });
    play(stretch, 0, 0, keys.length * KEY, { typing: true, what: `typing, ${keys.length} keys`, src: keys.map((k, i) => ({ t: i * KEY, v: k + 0.02 })) });
    part(stretch, keys[keys.length - 1] + 0.02, len(stretch), { what: 'read and sent' });
  };
  // A wait the cut leaves out, for the notes of the clip.
  const skip = (what, seconds) => { if (seconds > 0.05) leftOut.push({ what, seconds: Number(seconds.toFixed(1)) }); };
  return { shots, leftOut, len, play, part, whole, start, end, typing, skip, at: footage.at, has: footage.has };
}

module.exports = {
  // "A node created and edited" (clip-nodes.cjs): a request in the chat
  // becomes a whiteboard, its card is opened, and the board is changed by
  // hand and saves itself.
  nodes(footage) {
    const b = builder(footage);
    b.typing('ask', 'ask', { lead: 0.8 });
    const card = b.at('card', 'wait'), answer = b.at('answer', 'wait');
    if (card === null) throw new Error('the take has no card of a node');
    b.start('wait', 0.5, { what: 'sent' });
    // The assistant at work: its first message is on screen while the card
    // comes in, then (the wait left out) its answer.
    b.skip('the assistant makes the whiteboard', card - 0.6 - 0.5);
    b.part('wait', card - 0.6, card + 1.0, { dissolve: true, what: 'its message, then the card of the whiteboard' });
    // A gap shorter than a second and a half plays through: a dissolve over
    // it would show the card twice while the conversation scrolls.
    if (answer !== null && answer - (card + 1.0) > 1.5) {
      b.skip('the assistant writes its answer', answer - 0.2 - (card + 1.0));
      b.part('wait', answer - 0.2, b.len('wait'), { dissolve: true, what: 'its answer' });
    } else {
      b.part('wait', card + 1.0, b.len('wait'), { what: 'its answer' });
    }
    b.whole('open', { what: 'the whiteboard is opened from its card' });
    b.whole('edit', { what: 'a box moved and a box renamed by hand; the board saves itself' });
    return { shots: b.shots, leftOut: b.leftOut, max: 16 };
  },

  // "The assistant uses an app" (clip-assistant.cjs): the Plugins catalog with
  // GitHub connected, then a question in the chat that the assistant answers
  // with the GitHub plugin. The conversation draws no steps; the line under
  // the assistant's name in the panel says "Working in GitHub" while it does.
  assistant(footage) {
    const b = builder(footage);
    // A short look at the catalog: it opens with the pointer already on its
    // way to GitHub's "Connected" mark.
    b.part('catalog', 0.4, b.len('catalog'), { what: 'the catalog: GitHub connected' });
    // The whole way from the catalog's close button to the field, so the
    // pointer does not jump.
    b.typing('ask', 'ask', { lead: 10 });
    const first = b.at('said', 'wait'), tool = b.at('tool', 'wait'), answer = b.at('answer', 'wait');
    if (tool === null || answer === null) throw new Error('the take has no step with the plugin or no answer');
    // Its first message counts only when it came before the step with the plugin.
    const said = first !== null && first <= tool ? first : null;
    b.start('wait', 0.5, { what: 'sent' });
    if (said !== null && tool - said <= 1.6) {
      // Its message coming in and its first step with the plugin, in one piece.
      b.skip('the assistant thinks', said - 0.3 - 0.5);
      b.part('wait', said - 0.3, tool + 1.5, { dissolve: true, what: 'its message; the panel: working in GitHub' });
    } else {
      // Its message is on screen by then: one shot of the step with the plugin.
      // clip-assistant.cjs films the wait with few frames until such a moment,
      // so the shot begins at the moment itself.
      b.skip(said !== null ? 'the assistant thinks and writes its first message' : 'the assistant thinks', tool - 0.05 - 0.5);
      b.part('wait', tool - 0.05, tool + 1.6, { dissolve: true, what: said !== null ? 'its message on screen; the panel: working in GitHub' : 'the panel: working in GitHub' });
    }
    const after = said !== null && tool - said <= 1.6 ? tool + 1.5 : tool + 1.6;
    b.skip('the assistant works in GitHub and writes its answer', answer - 0.05 - after);
    b.part('wait', answer - 0.05, b.len('wait'), { dissolve: true, what: 'its answer' });
    b.whole('answer', { what: 'the answer, read' });
    return { shots: b.shots, leftOut: b.leftOut, max: 16 };
  },
};
