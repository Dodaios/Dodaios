// The cut of the PHONE clip: the phone app on the conversation that began at
// the desk, a look back at it, a request typed on the phone, the assistant
// waiting for a yes on an approval card, a tap on Allow, and its answer.
// phone-film.html draws it; phone-render.cjs loads it (FILM_EDIT=edit-phone.js).
//
// The rules of a README recording: the take in its own order, nothing laid
// over it. A wait for the model is left out (the picture before it dissolves
// into the one after it) and the typing plays at an even pace. Everything
// else plays at the speed it was filmed at; while a card is read nothing on
// the screen moves, so only that pause is shortened. What the shots are too
// long for LENGTH seconds is taken off all of them alike, and the cut refuses
// to go further than a quarter faster. Footage is named by the stretches
// phone-take.cjs filmed: open, hold-wait-<n>, card-<n>, answer.
window.EDIT = (footage) => {
  const W = footage.WIN.width;
  const FULL = [0, 0, W];           // the part of the screen shown: left, top, width
  const KEY = 0.09;                 // seconds a typed key: a quick thumb
  const DISSOLVE = 0.3;
  const BEFORE_LOOK = 0.35;         // the conversation as the phone opens, before the thumb moves
  const READ = 1.0;                 // a card is seen this long before Allow is tapped
  const SETTLED = 0.5;              // "Allowed" is seen this long when no card follows at once
  const WORKING = 0.55;             // the request in the conversation, "Working..." under the title
  const ANSWER = 2.1;               // the answer, read
  const LENGTH = 14;                // the longest the clip may be, in seconds
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
  // Footage at the speed it was filmed at, between two of its seconds.
  const part = (stretch, from, to, o) => {
    const a = Math.max(0, from), b = Math.min(len(stretch), to);
    play(stretch, a, b, b - a, o);
  };
  // Typing, a key every `pace` seconds: `keys` are the seconds of the stretch
  // at which each key was pressed.
  const typing = (stretch, keys, pace) => play(stretch, 0, 0, keys.length * pace, { src: keys.map((k, i) => ({ t: i * pace, v: k + 0.02 })) });

  // ---- 1  a look back, and the request, typed and sent ------------------------------
  const keys = footage.keys('ask', 'open');
  if (!keys.length) throw new Error('the take has no typed request');
  const look = footage.at('look', 'open');             // the thumb begins to drag
  const sent = footage.at('sent', 'open');             // the request is in the conversation
  part('open', look - BEFORE_LOOK, keys[0]);           // up to the desk, down again, the box tapped
  typing('open', keys, KEY);
  part('open', keys[keys.length - 1] + 0.02, sent + WORKING);   // Send tapped, the request in, "Working..."

  // ---- 2  every card: read for a moment, Allow tapped -------------------------------
  let following = false;   // the card came while the one before settled: no wait to leave out
  for (let n = 1; footage.has('card-' + n); n++) {
    const name = 'card-' + n;
    const allow = footage.at('allow-' + n, name);
    const allowed = footage.at('allowed-' + n, name);
    const next = footage.at('next-' + n, name);
    const from = Math.max(0, allow - READ);
    const to = next !== null && next >= 0 ? len(name) : allowed + SETTLED;
    part(name, from, to, { dissolve: !following });
    following = next !== null && next >= 0;
  }

  // ---- 3  the answer ------------------------------------------------------------------
  part('answer', 0, ANSWER, { dissolve: !following });

  // What the shots are longer than LENGTH is taken off all of them alike.
  const k = Math.min(1, LENGTH / t);
  if (k < 0.8) throw new Error(`the shots are ${t.toFixed(1)} s long: more than a quarter too long for ${LENGTH} s, shorten a shot`);
  for (const shot of shots) {
    shot.t0 *= k; shot.t1 *= k; shot.fade *= k;
    shot.src = shot.src.map((key) => ({ ...key, t: key.t * k }));
  }
  const duration = t * k;

  return {
    duration,
    stretch: k,
    black: [{ t: 0, v: 0 }, { t: duration, v: 0 }],
    shots,
  };
};
