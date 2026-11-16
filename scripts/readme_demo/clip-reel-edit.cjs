// The cut of the clip at the top of the README: one request to the assistant,
// two coding agents side by side in the Agentic IDE, a slide the assistant
// made, the confirmation of a deletion, and the report. clip-reel-cut.cjs
// turns it into the video.
//
// The rules are the ones of every README clip: the take in its own order,
// nothing laid over it. A wait for a model is left out (the picture before it
// dissolves into the one after it) and typing plays at an even pace.
// Everything else plays at the speed it was filmed at.
//
// The stretches and moments are those of clip-reel-take.cjs. The numbers
// below (how long each shot is shown) were chosen on the take of
// 16 November 2026; another take may need others. CUT_* variables change
// them without editing this file.
const KEY = Number(process.env.CUT_KEY || 0.036);   // seconds a typed key

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
  reel(footage) {
    const b = builder(footage);
    const need = (mark, stretch) => { const v = b.at(mark, stretch); if (v === null) throw new Error(`the take has no "${mark}" in "${stretch}"`); return v; };

    // 1. The request, typed and sent.
    b.typing('ask', 'ask', { lead: num('CUT_LEAD', 0.55) });
    b.part('start', 0, num('CUT_SENT', 0.45), { what: 'sent' });

    // 2. The assistant says what it will do; the two agents' chips come in.
    const agents = need('agents', 'start');
    b.skip('the assistant plans and starts two coding agents', agents - 0.45 - 0.4);
    b.part('start', agents + num('CUT_AGENTS_FROM', -0.4), agents + num('CUT_AGENTS_TO', 0.75), { dissolve: true, what: 'its answer, and the chips of two coding agents' });

    // 3. A click on the first chip: its thread in the Agentic IDE. The second
    //    agent's thread is opened beside it.
    b.part('to-ide', num('CUT_TOIDE_FROM', 0), b.len('to-ide'), { what: 'a click on the first chip: the Agentic IDE' });
    const columns = need('columns', 'beside');
    b.part('beside', 0, columns + num('CUT_COLUMNS', 1.3), { what: 'the second thread opened beside the first' });

    // 4. Both at work, then (the wait left out) both finished.
    const done = need('both-done', 'work');
    b.skip('the two agents work', done - 1.0);
    b.part('work', done + num('CUT_DONE_FROM', -0.4), done + num('CUT_DONE_TO', 1.5), { dissolve: true, what: 'both agents have finished' });

    // 5. Back to the conversation.
    b.part('to-chat', 0, need('chat', 'to-chat') + num('CUT_CHAT', 0.5), { what: 'back to the chat' });

    // 6. The deck and the approval, in the order they came.
    for (const round of ['chat-1', 'chat-2']) {
      if (!b.has(round)) continue;
      const card = b.at('card', round), approval = b.at('approval', round);
      const inRound = (v) => v !== null && v >= 0 && v <= b.len(round) + 0.5;
      if (inRound(card) && b.has('deck')) {
        b.skip('the assistant checks the work and makes the slide', card);
        b.part(round, card + num('CUT_CARD_FROM', -0.3), b.len(round), { dissolve: true, what: 'the card of the slide comes in' });
        const clicked = need('clicked', 'deck'), page = need('page', 'deck'), closed = need('closed', 'deck');
        // The stage is empty for a moment before it draws the deck: left out.
        b.part('deck', 0, clicked + num('CUT_CLICKED', -0.02), { what: 'the pointer to the card, a click' });
        // CUT_DECK_SKIP="2.4,2.9": seconds of the stretch in which the slide only
        // stands and the pointer rests; they are left out without a dissolve.
        const rest = (process.env.CUT_DECK_SKIP || '').split(',').map(Number);
        if (rest.length === 2 && rest[1] > rest[0] && rest[0] > page) {
          b.part('deck', page + 0.01, rest[0], { dissolve: true, what: 'the slide, large' });
          b.skip('the slide stands', rest[1] - rest[0]);
          b.part('deck', rest[1], closed + num('CUT_CLOSED', 0.12), { what: 'back to the chat by the rail' });
        } else {
          b.part('deck', page + 0.01, closed + num('CUT_CLOSED', 0.12), { dissolve: true, what: 'the slide, large; back to the chat by the rail' });
        }
      } else if (inRound(approval) && b.has('approve')) {
        b.skip('the assistant gets to the deletion', approval);
        b.part(round, approval + num('CUT_APPROVAL_FROM', -0.3), b.len(round), { dissolve: true, what: 'the confirmation card of the deletion' });
        b.part('approve', num('CUT_APPROVE_FROM', 0), need('allowed', 'approve') + num('CUT_ALLOWED', 0.7), { what: 'the pointer to "Allow once", a click' });
      }
    }

    // 7. The report.
    // The assistant may say several things after the deletion: CUT_REPORT_N
    // picks which of its messages the clip ends on (0 is the first).
    const reports = b.ats('report', 'report');
    if (!reports.length) throw new Error('the take has no report');
    const report = reports[Math.min(reports.length - 1, num('CUT_REPORT_N', 0))];
    b.skip('the assistant deletes the folder and writes its report', report);
    b.part('report', report + num('CUT_REPORT_FROM', -0.3), report + num('CUT_REPORT_TO', 3.2), { dissolve: true, what: 'the report' });
    // The loop: the last picture dissolves into the first one.
    const first = b.shots[0].src[0].v;
    b.play('ask', first, first, num('CUT_LOOP', 0.3), { dissolve: true, what: 'into the first picture (the loop)' });
    return { shots: b.shots, leftOut: b.leftOut, max: Number(process.env.CUT_MAX || 30) };
  },
};
