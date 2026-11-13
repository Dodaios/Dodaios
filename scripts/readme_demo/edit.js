// The README video's cut: which footage is on screen when, and how fast it
// plays. film.html draws it.
//
// The video is the take in its own order, without anything laid over it. A
// cut does three things only: it plays the typing at an even pace, it leaves
// out the wait for a model (the picture before the wait dissolves into the
// one in which the answer comes), and it plays the rest a little faster.
// Footage is named by the stretches record.cjs filmed.
window.EDIT = (footage) => {
  const W = footage.WIN.width, H = footage.WIN.height;
  const FULL = [0, 0, W];           // the part of the window shown: left, top, width
  const KEY = 0.024;                // seconds a typed key
  const DISSOLVE = 0.32;
  const len = (name) => footage.length(name);

  const shots = [];
  let t = 0;
  // `stretch` from second `from` to second `to`, played in `seconds`.
  const play = (stretch, from, to, seconds, o = {}) => {
    if (!footage.has(stretch) || seconds <= 0) return;
    const src = o.src || [{ t: 0, v: from }, { t: seconds, v: to }];
    // The shot before stays under a dissolve until it is over.
    if (o.dissolve && shots.length) shots[shots.length - 1].t1 += DISSOLVE;
    shots.push({ stretch, t0: t, t1: t + seconds, src, cam: [{ t: 0, v: FULL }], fade: o.dissolve ? DISSOLVE : 0 });
    t += seconds;
  };
  const after = (stretch, seconds, o) => play(stretch, 0, len(stretch), seconds, o);

  // A request to Dodaios: the pointer goes to the box, the request is typed
  // at an even pace and sent, and its bubble stands in the conversation.
  // `tail` is how much of the wait is shown before the cut to the answer.
  const ask = (name, lead = 0.55, tail = 0.5) => {
    const keys = footage.keys(name);
    const stretch = 'ask-' + name;
    play(stretch, keys[0] - 0.8, keys[0], lead);
    play(stretch, 0, 0, keys.length * KEY, { src: keys.map((k, i) => ({ t: i * KEY, v: k + 0.02 })) });
    play(stretch, keys[keys.length - 1] + 0.02, len(stretch), 0.85);
    play('wait-' + name, 0, tail, tail * 0.9);
  };
  // The answer: from `before` seconds ahead of the moment Dodaios was done to `past` seconds after it.
  const answer = (name, before, past, seconds) => {
    const done = footage.at('done-' + name, 'wait-' + name);
    play('wait-' + name, done - before, done + past, seconds, { dissolve: true });
  };

  // ---- 1  a question, answered from a file on the computer --------------------
  ask('numbers', 0.9);
  answer('numbers', 2.2, 1.6, 2.6);
  after('answer-numbers', 4.0);              // up to the chart, the pointer on a bar

  // ---- 2  the answer as a page --------------------------------------------------
  ask('page', 0.55, 0);                      // cut at once: a notice of the app's own stood there for a moment
  answer('page', 6.5, -2.3, 2.6);            // the card of the page comes, then its word about it
  after('card', 2.9);                        // up to the card, and the click on it
  after('page', 3.9);                        // the page, scrolled
  after('to-chat', 1.3);

  // ---- 3  something it keeps looking after --------------------------------------
  ask('task');
  answer('task', 1.7, 1.5, 2.2);
  after('answer-task', 1.5);

  // ---- 4  a fault: checked, and handed to a coding agent ------------------------
  ask('fix');
  play('wait-fix', len('wait-fix') - 1.5, len('wait-fix'), 1.1, { dissolve: true });   // the agent shows under "Recent activity"
  after('started', 2.2);                     // the click on it: into the Agentic IDE
  after('thread', 6.2);                      // the agent at work, to its end
  after('done', 0.9);
  after('review', 5.6);                      // its changes, reviewed
  after('to-report', 1.4);                   // back to Dodaios
  after('report', 2.6);

  // The video is as long as its music: every shot is stretched by the same
  // little bit so that the two end together.
  const LENGTH = 55.3;
  const k = LENGTH / t;
  for (const shot of shots) {
    shot.t0 *= k; shot.t1 *= k;
    shot.src = shot.src.map((key) => ({ ...key, t: key.t * k }));
  }

  return {
    duration: LENGTH,
    stretch: k,
    black: [{ t: 0, v: 0 }, { t: LENGTH - 0.7, v: 0 }, { t: LENGTH - 0.05, v: 1 }],
    shots,
  };
};
