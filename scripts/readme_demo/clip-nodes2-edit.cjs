// The cut of the second Nodes clip of the README (a slide deck made from one
// sentence and changed by hand). clip-nodes2-cut.cjs turns it into the video.
// A copy of nodes-plugins-edit.cjs with the cut of clip-nodes2-take.cjs.
//
// The rules are the ones of the clip at the top of the README: the take in
// its own order, nothing laid over it. A wait for a model is left out (the
// picture before it dissolves into the one after it) and typing plays at an
// even pace. Everything else plays at the speed it was filmed at. A clip has
// a longest length (`max`); what its shots are longer is taken off all of them
// alike by the cutter, which refuses more than a quarter.

// Seconds a typed key in the video: the request in the chat field, and the
// slide's new title typed by hand (the take types them about as fast; the cut
// only makes the pace even, whatever the computer was busy with meanwhile).
const KEY = 0.055;
const HAND_KEY = 0.062;

function builder(footage) {
  const shots = [];
  const leftOut = [];
  const len = (name) => footage.length(name);
  const play = (stretch, from, to, seconds, o = {}) => {
    if (!footage.has(stretch) || seconds <= 0.001) return;
    shots.push({ stretch, seconds, src: o.src || [{ t: 0, v: Math.max(0, from) }, { t: seconds, v: to }], dissolve: Boolean(o.dissolve), typing: Boolean(o.typing), what: o.what || '' });
  };
  const part = (stretch, from, to, o) => {
    const a = Math.max(0, from), b = Math.min(len(stretch), to);
    play(stretch, a, b, b - a, o);
  };
  const whole = (stretch, o) => part(stretch, 0, len(stretch), o);
  const start = (stretch, seconds, o) => part(stretch, 0, seconds, o);
  // A text typed in `stretch` between its seconds `from` and `to`: the way to
  // the field, the typing at an even pace, and what follows the last key.
  const typing = (stretch, name, { from = 0, to = len(stretch), lead = 1.0, key = KEY, what = '' } = {}) => {
    const keys = footage.keys(name, stretch);
    if (!keys.length) { part(stretch, from, to); return; }
    part(stretch, Math.max(from, keys[0] - lead), keys[0], { what: what || 'to the field' });
    play(stretch, 0, 0, keys.length * key, { typing: true, what: `typing, ${keys.length} keys`, src: keys.map((k, i) => ({ t: i * key, v: k + 0.02 })) });
    part(stretch, keys[keys.length - 1] + 0.02, to, { what: 'after the last key' });
  };
  const skip = (what, seconds) => { if (seconds > 0.05) leftOut.push({ what, seconds: Number(seconds.toFixed(1)) }); };
  return { shots, leftOut, len, play, part, whole, start, typing, skip, at: footage.at, has: footage.has };
}

module.exports = {
  nodes(footage) {
    const b = builder(footage);
    // 1. The request, typed into the chat field and sent.
    b.typing('ask', 'ask', { lead: 0.6, to: b.len('ask') });
    b.start('wait', 0.4, { what: 'sent' });
    // 2. The assistant at work: the wait is left out; the card of the deck
    //    comes into the conversation, then (another wait left out) the answer.
    const card = b.at('card', 'wait'), answer = b.at('answer', 'wait');
    if (card === null) throw new Error('the take has no card of a node');
    b.skip('the assistant makes the deck', card - 0.5 - 0.4);
    b.part('wait', card - 0.5, card + 1.1, { dissolve: true, what: 'the card of the deck comes in' });
    // The answer under the card is not waited for: the card dissolves into
    // the conversation as it stands when the card is clicked, answer and all.
    b.skip('the assistant writes its answer', b.len('wait') - (card + 1.1));
    // 3. The deck opened from its card: its page on the stage.
    // The stage is empty for a moment before the deck's page is drawn (it
    // even says "Nothing here yet"): that is left out, the card dissolves
    // into the page.
    const clicked = b.at('clicked', 'open'), page = b.at('page', 'open');
    if (clicked !== null && page !== null) {
      b.part('open', 0, clicked + 0.1, { dissolve: true, what: 'the pointer to the card, a click' });
      b.skip('the stage draws the deck', page + 0.01 - (clicked + 0.1));
      b.part('open', page + 0.01, b.len('open'), { dissolve: true, what: 'the deck on the stage' });
    } else {
      b.whole('open', { dissolve: true, what: 'the deck opened from its card' });
    }
    // 4. A click on the title opens the editor; the title is typed over by
    //    hand and the editor saves. The clip ends a moment after "saved".
    const saved = b.at('saved', 'edit');
    b.typing('edit', 'title', { lead: 99, key: HAND_KEY, to: saved !== null ? Math.min(b.len('edit'), saved + 0.75) : b.len('edit'), what: 'the editor opens; into the title' });
    return { shots: b.shots, leftOut: b.leftOut, max: Number(process.env.CUT_MAX || 14) };
  },
};
