// The cut of the second Assistant clip of the README (a copy of
// nodes-plugins-edit.cjs with its own cut). clip-assistant2-cut.cjs turns it
// into the video.
//
// The rules are the ones of the clip at the top of the README (edit-agents.js):
// the take in its own order, nothing laid over it. A wait for a model is left
// out (the picture before it dissolves into the one after it) and the typing
// plays at an even pace. Everything else plays at the speed it was filmed at.
// A clip has a longest length (`max`); what its shots are longer is taken off
// all of them alike by the cutter, which refuses more than a quarter.
//
// Footage is named by the stretches clip-assistant2-assistant.cjs films.

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
  // "The assistant does the work" (clip-assistant2-assistant.cjs): a question
  // about a bank export on the computer, typed and sent; the answer comes with
  // a chart, and the pointer reads the chart's columns.
  assistant(footage) {
    const b = builder(footage);
    // From the still picture before the pointer sets off (the take waits
    // 0.3 s), the whole way to the field.
    const keys = footage.keys('ask', 'ask');
    const REST = 0.25;
    b.typing('ask', 'ask', { lead: keys.length ? keys[0] - REST : 1.0 });
    const said = b.at('said', 'wait'), chart = b.at('chart', 'wait');
    if (chart === null) throw new Error('the take has no chart');
    b.start('wait', 0.3, { what: 'sent' });
    let from;
    if (said !== null && said < chart - 2.5) {
      // Its first message on its own, then (the work left out) the chart.
      b.skip('the assistant starts', said - 0.2 - 0.3);
      b.part('wait', said - 0.2, said + 1.0, { dissolve: true, what: 'its first message' });
      from = chart - 0.35;
      b.skip('the assistant reads the file and adds up the numbers', from - (said + 1.0));
    } else {
      from = (said !== null ? Math.min(said, chart) : chart) - 0.35;
      b.skip('the assistant reads the file and adds up the numbers', from - 0.3);
    }
    b.part('wait', from, b.len('wait'), { dissolve: true, what: 'its answer and the chart' });
    b.part('answer', 0, b.len('answer') - 0.5, { what: 'the chart read: each column shows its value' });
    // The loop: back into the clip's first picture.
    b.part('ask', 0, REST, { dissolve: true, what: 'back to the first picture, for the loop' });
    return { shots: b.shots, leftOut: b.leftOut, max: 12.5 };
  },
};
