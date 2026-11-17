// The cut of the video at the top of the README: the assistant hands two
// Claude Code terminals their tasks by call sign, makes a slide from what it
// remembers, asks before a permanent deletion, and shows what it remembers.
// clip-video-cut.cjs turns it into the video.
//
// The rules are the ones of every README clip: the take in its own order,
// nothing laid over it. A wait for a model is left out (the picture before it
// dissolves into the one after it) and typing plays at an even pace.
// Everything else plays at the speed it was filmed at.
//
// The stretches and moments are those of clip-video-take.cjs. CUT_* variables
// change the numbers without editing this file.
const KEY = Number(process.env.CUT_KEY || 0.05);   // seconds a typed key

const num = (name, fallback) => (process.env[name] !== undefined && process.env[name] !== '' ? Number(process.env[name]) : fallback);

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
  const typing = (stretch, name, { from = 0, to = len(stretch), lead = 1.0, key = KEY, what = '' } = {}) => {
    const keys = footage.keys(name, stretch);
    if (!keys.length) { part(stretch, from, to); return; }
    part(stretch, Math.max(from, keys[0] - lead), keys[0], { what: what || 'to the field' });
    play(stretch, 0, 0, keys.length * key, { typing: true, what: `typing, ${keys.length} keys`, src: keys.map((k, i) => ({ t: i * key, v: k + 0.02 })) });
    part(stretch, keys[keys.length - 1] + 0.02, to, { what: 'after the last key' });
  };
  const skip = (what, seconds) => { if (seconds > 0.05) leftOut.push({ what, seconds: Number(seconds.toFixed(1)) }); };
  return { shots, leftOut, len, play, part, typing, skip, at: footage.at, ats: footage.ats, has: footage.has };
}

module.exports = {
  video(footage) {
    const b = builder(footage);
    const need = (mark, stretch) => { const v = b.at(mark, stretch); if (v === null) throw new Error(`the take has no "${mark}" in "${stretch}"`); return v; };
    const sent = (name) => need(name + '-sent', name);

    // 1. T1 and T2 get their tasks by call sign.
    b.typing('grid-ask', 'grid-ask', { lead: num('CUT_LEAD', 0.8), to: sent('grid-ask') + 0.7 });
    const said = need('said', 'grid-said');
    b.skip('the assistant hands T1 and T2 their tasks', said);
    b.part('grid-said', said - 0.3, said + num('CUT_SAID', 3.2), { dissolve: true, what: "the assistant's answer" });

    // 2. The Grid: T1 and T2 at work side by side, then both done.
    const grid = need('grid', 'to-grid');
    b.part('to-grid', 0, Math.min(grid, num('CUT_IDE', 2.2)), { dissolve: true, what: 'to the IDE' });
    if (grid > num('CUT_IDE', 2.2) + 1.2) {
      b.skip('the IDE opens its Grid', grid - 1.0 - num('CUT_IDE', 2.2));
      b.part('to-grid', grid - 1.0, b.len('to-grid'), { dissolve: true, what: 'the Grid: T1 and T2 at work' });
    } else b.part('to-grid', Math.min(grid, num('CUT_IDE', 2.2)), b.len('to-grid'), { what: 'the Grid: T1 and T2 at work' });
    const done = need('both-done', 'grid-work');
    const live = Math.min(num('CUT_LIVE', 6), done - 2);
    if (done - 1.2 - live < 3) {
      b.part('grid-work', 0, done + num('CUT_DONE', 3.5), { what: 'both at work, then both done' });
    } else {
      b.part('grid-work', 0, live, { what: 'both at work' });
      b.skip('T1 and T2 work', done - 1.2 - live);
      b.part('grid-work', done - 1.2, done + num('CUT_DONE', 3.5), { dissolve: true, what: 'both done' });
    }

    // 3. The slide for Sam, from what the assistant remembers about Sam.
    b.part('to-chat', 0, b.len('to-chat'), { what: 'back to the chat' });
    b.typing('sam-ask', 'sam-ask', { lead: 0.6, to: sent('sam-ask') + 0.6 });
    const card = need('card', 'sam-wait');
    b.skip('the assistant makes the slide', card);
    b.part('sam-wait', card - 0.3, card + num('CUT_CARD', 2.2), { dissolve: true, what: 'the card of the slide comes in' });
    b.part('sam-deck', 0, b.len('sam-deck'), { what: 'the slide, large; back to the chat' });

    // 4. A permanent deletion asks first.
    b.typing('del-ask', 'del-ask', { lead: 0.6, to: sent('del-ask') + 0.6 });
    // The card comes in del-wait, or in del-wait-2 when another card was
    // answered first (left out).
    const cardIn = b.has('del-wait-2') ? 'del-wait-2' : 'del-wait';
    const approval = need('approval', cardIn);
    b.skip('the assistant gets to the deletion', approval);
    b.part(cardIn, approval - 0.3, b.len(cardIn), { dissolve: true, what: 'the confirmation card' });
    const allowed = need('allowed', 'del-allow');
    const fin = b.at('done', 'del-allow');
    if (fin !== null && fin < b.len('del-allow')) {
      b.part('del-allow', 0, allowed + 0.8, { what: 'the pointer to "Allow once", a click' });
      b.skip('the assistant deletes the folder', fin - allowed - 0.8);
      b.part('del-allow', fin - 0.3, fin + num('CUT_FIN', 3.2), { dissolve: true, what: "the assistant's answer" });
    } else {
      // A take that stopped after the deletion, with a pick-up of the end
      // (clip-video-take.cjs with DEMO_FROM=memory, merged by
      // clip-video-merge.py): the answer as filmed, then the pick-up.
      b.part('del-allow', 0, allowed + num('CUT_ANSWER', 3.3), { what: 'the click, the deletion, the answer' });
      b.part('del-end', 0, b.len('del-end'), { dissolve: true, what: 'the answer (pick-up)' });
    }

    // 5. What the assistant remembers.
    b.part('memory', 0, b.len('memory'), { what: 'Search, Memory' });
    const shown = need('memory-shown', 'memory-list');
    b.skip('the list of memories loads', shown);
    b.part('memory-list', shown - 0.05, b.len('memory-list'), { dissolve: shown > 0.4, what: 'what the assistant remembers' });
    return { shots: b.shots, leftOut: b.leftOut, max: Number(process.env.CUT_MAX || 120) };
  },
};
