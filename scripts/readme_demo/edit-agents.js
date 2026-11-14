// The cut of the agents clip, the 30 seconds at the top of the README.
// film.html draws it; render.cjs loads it with FILM_EDIT=edit-agents.js.
//
// The same rules as the longer film (edit.js): the take in its own order,
// nothing laid over it. The typing plays at an even pace, a wait for a model
// is left out (the picture before it dissolves into the one after it), and
// the rest plays a little faster. Footage is named by the stretches the
// "agents" part of record.cjs filmed.
window.EDIT = (footage) => {
  const W = footage.WIN.width;
  const FULL = [0, 0, W];           // the part of the window shown: left, top, width
  const KEY = 0.026;                // seconds a typed key
  const DISSOLVE = 0.3;
  const len = (name) => footage.length(name);

  const shots = [];
  let t = 0;
  // `stretch` from second `from` to second `to`, played in `seconds`.
  const play = (stretch, from, to, seconds, o = {}) => {
    if (!footage.has(stretch) || seconds <= 0) return;
    const src = o.src || [{ t: 0, v: Math.max(0, from) }, { t: seconds, v: to }];
    // The shot before stays under a dissolve until it is over.
    if (o.dissolve && shots.length) shots[shots.length - 1].t1 += DISSOLVE;
    shots.push({ stretch, t0: t, t1: t + seconds, src, cam: [{ t: 0, v: FULL }], fade: o.dissolve ? DISSOLVE : 0 });
    t += seconds;
  };
  const whole = (stretch, seconds, o) => play(stretch, 0, len(stretch), seconds, o);
  // The first `real` seconds of a stretch.
  const start = (stretch, real, seconds, o) => play(stretch, 0, Math.min(real, len(stretch)), seconds, o);
  // The last `real` seconds of a stretch: what a wait ended in.
  const end = (stretch, real, seconds, o) => play(stretch, len(stretch) - Math.min(real, len(stretch)), len(stretch), seconds, o);

  // ---- 1  the request -----------------------------------------------------------
  const keys = footage.keys('review');
  play('ask-review', keys[0] - 0.8, keys[0], 0.6);                 // the pointer goes to the box
  play('ask-review', 0, 0, keys.length * KEY, { src: keys.map((k, i) => ({ t: i * KEY, v: k + 0.02 })) });
  play('ask-review', keys[keys.length - 1] + 0.02, len('ask-review'), 0.75);   // read, then sent
  play('wait-review', 0, 0.45, 0.4);                               // its bubble stands in the conversation
  whole('ack', 0.9, { dissolve: true });                           // the first words of Dodaios

  // ---- 2  into the Agentic IDE: a thread for each pull request --------------------
  whole('to-ide', 1.1);
  end('starting', 3.0, 1.6, { dissolve: true });                   // the first agents come into the list

  // ---- 3  three of the agents at work ----------------------------------------------
  // Each look is the click on a thread, and then the agent's next step: the
  // wait for that step is left out, as every wait for a model is.
  ['watch-1', 'watch-2', 'watch-3'].forEach((look, n) => {
    if (!footage.has(look)) return;
    const step = footage.at('step-' + (n + 1), look);
    const to = Math.min(len(look), step + 2.4);
    if (step - 1.0 <= 1.6) { play(look, 0, to, Math.max(2.3, to / 1.5)); return; }   // the step came at once
    start(look, 1.5, 1.05);                                        // the click, the thread opens
    play(look, step - 1.0, to, 2.3, { dissolve: true });           // its next step
  });
  // The last ones finish. When they had all finished during the third look,
  // there is nothing to wait for.
  if (len('finishing') >= 1.5) end('finishing', 2.4, 1.5, { dissolve: true });
  end('done', 1.2, 0.8);

  // ---- 4  back to Dodaios: the report and its answer -------------------------------
  whole('to-chat', 1.15);
  // From the card of the report to the answer under it, and a moment to read.
  const answered = footage.at('answer', 'report');
  play('report', 0, Math.min(len('report'), answered + 2.3), 4.8, { dissolve: true });

  // ---- 5  the report itself ----------------------------------------------------------
  whole('open-report', 1.2);
  whole('page', 4.3);

  // Thirty seconds: every shot is stretched by the same little bit.
  const LENGTH = 30;
  const k = LENGTH / t;
  for (const shot of shots) {
    shot.t0 *= k; shot.t1 *= k;
    shot.src = shot.src.map((key) => ({ ...key, t: key.t * k }));
  }

  return {
    duration: LENGTH,
    stretch: k,
    black: [{ t: 0, v: 0 }, { t: LENGTH - 0.45, v: 0 }, { t: LENGTH - 0.03, v: 1 }],
    shots,
  };
};
