// The cut of the video at the top of the README: a short exchange with the
// assistant, then the assistant starts a coding agent whose chat is followed
// in the Agentic IDE, and the assistant reports back. clip-video-cut.cjs
// turns it into the video.
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

    // 1. An ordinary question to the assistant, and its answer.
    b.typing('chat-ask', 'chat-ask', { lead: num('CUT_LEAD', 0.8), to: sent('chat-ask') + 0.6 });
    const answer = need('chat-said', 'chat-wait');
    b.skip('the assistant answers', answer);
    b.part('chat-wait', answer - 0.3, answer + num('CUT_ANSWER', 3.5), { dissolve: true, what: "the assistant's answer" });

    // 2. The assistant is asked to have Claude Code make a change.
    b.typing('hand-ask', 'hand-ask', { lead: 0.6, to: sent('hand-ask') + 0.6 });
    const said = need('said', 'hand-wait');
    b.skip('the assistant starts the agent', said);
    b.part('hand-wait', said - 0.3, said + num('CUT_SAID', 3.2), { dissolve: true, what: "the assistant's answer" });

    // 3. The Agentic IDE: the agent's chat at work, then done.
    b.part('to-ide', 0, b.len('to-ide'), { what: "to the IDE, the agent's chat" });
    {
      const end = need('hand-done', 'hand-work');
      const files = b.at('ide-files', 'hand-work');
      const live = num('CUT_LIVE', 6);
      if (files !== null && files > live + 3 && files < end - 4) {
        b.part('hand-work', 0, live, { what: 'the agent at work' });
        b.skip('the agent works', files - 1.2 - live);
        b.part('hand-work', files - 1.2, files + 2.5, { dissolve: true, what: 'the changed files' });
        b.skip('the agent finishes', end - 1.2 - files - 2.5);
        b.part('hand-work', end - 1.2, end + num('CUT_DONE', 3.5), { dissolve: true, what: 'the agent is done' });
      } else if (end - 1.2 - live < 2.5) {
        b.part('hand-work', 0, end + num('CUT_DONE', 3.5), { what: 'the agent at work, then done' });
      } else {
        b.part('hand-work', 0, live, { what: 'the agent at work' });
        b.skip('the agent works', end - 1.2 - live);
        b.part('hand-work', end - 1.2, end + num('CUT_DONE', 3.5), { dissolve: true, what: 'the agent is done' });
      }
    }

    // 4. Back to the assistant: its report.
    b.part('back', 0, b.len('back'), { what: 'back to the assistant' });
    const report = need('report', 'back-wait');
    if (report > 0.6) b.skip('the assistant reads the chat', report);
    b.part('back-wait', Math.max(0, report - 0.3), b.len('back-wait'), { dissolve: report > 0.6, what: "the assistant's report" });
    return { shots: b.shots, leftOut: b.leftOut, max: Number(process.env.CUT_MAX || 120) };
  },
};
