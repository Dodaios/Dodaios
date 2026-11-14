// The cut of the agents clip, the 30 seconds at the top of the README.
// film.html draws it; render.cjs loads it with FILM_EDIT=edit-agents.js.
//
// The same rules as the longer film (edit.js): the take in its own order,
// nothing laid over it. A wait for a model is left out (the picture before it
// dissolves into the one after it) and the typing plays at an even pace.
// Unlike that film, everything else plays at the speed it was filmed at: an
// earlier cut played its shots up to twice as fast, and with the pointer
// jumping it looked like a slide show. What the shots are too long for thirty
// seconds is taken off all of them alike, and the cut refuses to go further
// than a quarter faster. Footage is named by the stretches the "agents" part
// of record.cjs filmed.
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
  // Footage at the speed it was filmed at: a whole stretch, its first seconds,
  // its last seconds, or the part between two of its seconds.
  const part = (stretch, from, to, o) => {
    const a = Math.max(0, from), b = Math.min(len(stretch), to);
    play(stretch, a, b, b - a, o);
  };
  const whole = (stretch, o) => part(stretch, 0, len(stretch), o);
  const start = (stretch, seconds, o) => part(stretch, 0, seconds, o);
  const end = (stretch, seconds, o) => part(stretch, len(stretch) - seconds, len(stretch), o);

  // ---- 1  the request -----------------------------------------------------------
  const keys = footage.keys('review');
  part('ask-review', keys[0] - 0.85, keys[0]);                     // the pointer goes to the box
  play('ask-review', 0, 0, keys.length * KEY, { src: keys.map((k, i) => ({ t: i * KEY, v: k + 0.02 })) });
  part('ask-review', keys[keys.length - 1] + 0.02, len('ask-review'));   // read, then sent
  start('wait-review', 0.4);                                       // its bubble stands in the conversation
  start('ack', 1.0, { dissolve: true });                           // the first words of Dodaios

  // ---- 2  the agents come up, and the way into the Agentic IDE ---------------------
  end('agents-in', 2.1, { dissolve: true });                       // under "Recent activity", one after the other
  whole('to-ide');                                                 // the first one's thread

  // ---- 3  two more of them beside it, and all three at work ------------------------
  // The end of each of these is the pointer resting in the new column.
  start('beside-1', len('beside-1') - 0.4);
  start('beside-2', len('beside-2') - 0.4);
  start('watching', 2.4);
  // The last ones finish. When they had all finished while they were watched,
  // there is nothing to wait for.
  if (len('finishing') >= 1.5) end('finishing', 1.0, { dissolve: true });
  end('done', 1.3, len('finishing') >= 1.5 ? {} : { dissolve: true });

  // ---- 4  back to Dodaios: the report and its answer -------------------------------
  whole('to-chat');
  // The card of the report comes; then, the wait for it left out, the answer
  // under the card and a moment to read it.
  const answered = footage.at('answer', 'report');
  start('report', Math.min(0.9, answered - 0.8), { dissolve: true });
  part('report', answered - 0.6, answered + 1.9, { dissolve: true });

  // ---- 5  the report itself ----------------------------------------------------------
  whole('open-report');
  whole('page');

  // Thirty seconds. What the shots are longer is taken off all of them alike.
  const LENGTH = 30;
  const k = LENGTH / t;
  if (k < 0.8) throw new Error(`the shots are ${t.toFixed(1)} s long: more than a quarter too long for ${LENGTH} s, shorten a shot`);
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
