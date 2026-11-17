// The cut of the video at the top of the README: Claude Code builds a change
// in the Agentic IDE's chat; the assistant turns it into a slide for a
// colleague (opened large) and hands the next task to a chat of its own in the
// IDE, which is watched at work; back to the assistant for its report.
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
    // A stretch of work: its first seconds as filmed, the wait left out, its
    // end from `mark` on.
    const work = (stretch, mark, { live = 5, after = 3.5, what = '' } = {}) => {
      const end = need(mark, stretch);
      if (end - 1.2 - live < 2.5) { b.part(stretch, 0, end + after, { what: what + ', at work, then done' }); return; }
      b.part(stretch, 0, live, { what: what + ', at work' });
      b.skip(what + ' works', end - 1.2 - live);
      b.part(stretch, end - 1.2, end + after, { dissolve: true, what: what + ', done' });
    };

    // 1. The Agentic IDE's chat in trailhead: Claude Code builds the change.
    b.typing('ide-ask', 'ide-ask', { lead: num('CUT_LEAD', 0.9), to: sent('ide-ask') + 1.0 });
    {
      const end = need('ide-done', 'ide-work');
      const files = b.at('ide-files', 'ide-work');
      const live = num('CUT_LIVE', 5);
      if (files !== null && files > live + 3 && files < end - 4) {
        b.part('ide-work', 0, live, { what: 'Claude Code at work' });
        b.skip('Claude Code works', files - 1.2 - live);
        b.part('ide-work', files - 1.2, files + 2.5, { dissolve: true, what: 'the changed files' });
        b.skip('Claude Code finishes', end - 1.2 - files - 2.5);
        b.part('ide-work', end - 1.2, end + num('CUT_DONE', 3.5), { dissolve: true, what: 'Claude Code is done' });
      } else work('ide-work', 'ide-done', { live, after: num('CUT_DONE', 3.5), what: 'Claude Code' });
    }

    // 2. The assistant: a slide for Sam, from what it remembers about Sam.
    b.part('to-chat', 0, b.len('to-chat'), { what: 'to the assistant' });
    b.typing('sam-ask', 'sam-ask', { lead: 0.6, to: sent('sam-ask') + 0.6 });
    const card = need('card', 'sam-wait');
    b.skip('the assistant makes the slide', card);
    b.part('sam-wait', card - 0.3, card + num('CUT_CARD', 2.2), { dissolve: true, what: 'the card of the slide comes in' });
    b.part('sam-deck', 0, b.len('sam-deck'), { what: 'the slide, large; back to the chat' });

    // 3. The assistant hands the next task to a chat of its own in the IDE.
    b.typing('hand-ask', 'hand-ask', { lead: 0.6, to: sent('hand-ask') + 0.6 });
    const said = need('said', 'hand-wait');
    b.skip('the assistant opens a chat in the IDE', said);
    b.part('hand-wait', said - 0.3, said + num('CUT_SAID', 3.2), { dissolve: true, what: "the assistant's answer" });
    b.part('to-ide', 0, b.len('to-ide'), { what: 'to the IDE, the chat the assistant started' });
    work('hand-work', 'hand-done', { live: num('CUT_LIVE2', 4), after: num('CUT_DONE2', 3.5), what: "the assistant's chat in the IDE" });

    // 4. Back to the assistant: its report.
    b.part('back', 0, b.len('back'), { what: 'back to the assistant' });
    const report = need('report', 'back-wait');
    if (report > 0.6) b.skip('the assistant reads the chat', report);
    b.part('back-wait', Math.max(0, report - 0.3), b.len('back-wait'), { dissolve: report > 0.6, what: "the assistant's report" });
    return { shots: b.shots, leftOut: b.leftOut, max: Number(process.env.CUT_MAX || 120) };
  },
};
