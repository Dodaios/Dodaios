// The cut of the hero clip, the recording at the top of the README: one
// request to the assistant that crosses three places of the app. The chat,
// the Agentic IDE with three coding agents side by side, and a node (a slide
// deck) that is opened and changed by hand.
// film.html draws it; render.cjs loads it with FILM_EDIT=edit-hero.js.
//
// The rules of a README recording: the take in its own order, nothing laid
// over it. A wait for a model is left out (the picture before it dissolves
// into the one after it) and typing plays at an even pace. Everything else
// plays at the speed it was filmed at. What the shots are too long for
// LENGTH seconds is taken off all of them alike, and the cut refuses to go
// further than a quarter faster. Footage is named by the stretches the
// "hero" part of record.cjs filmed.
//
// Where the pointer rests between two stretches, the shots join inside that
// rest without a dissolve: the picture is the same on both sides of the join
// (the pointer stands still, nothing else moves but a seconds counter), so
// only the length of the rest changes. A join never falls inside a movement.
// The seconds below are those of the take of 15 November 2026; a new take
// needs its own (look at a contact sheet of the stretches first).
window.EDIT = (footage) => {
  const W = footage.WIN.width;
  const FULL = [0, 0, W];           // the part of the window shown: left, top, width
  const KEY = 0.026;                // seconds a typed key of the request
  const HAND = 0.06;                // seconds a key of the title typed by hand
  const DISSOLVE = 0.3;
  const LENGTH = 33;                // the longest the clip may be, in seconds
  // "agents-in": the pointer reaches the first agent's line under "Recent
  // activity" about 1.2 s in and rests on it until the click, about 0.55 s
  // into "to-ide". A quarter of a second of that rest is kept on each side.
  const AGENT_TO = 1.45, IDE_FROM = 0.3;
  // "to-ide": the thread is open and the pointer has come to rest at 2.1 s.
  const IDE_TO = 2.35;
  // "watching": the pointer rests where "beside-2" left it until about 0.9 s.
  const WATCH_FROM = 0.6;
  // "done": the pointer goes over the finished reviews to the last column and
  // stops there; "to-chat" sets off from that place.
  const DONE_FROM = 3.3, DONE_TO = 4.85;
  // "deck": the pointer comes to rest over the slide about 0.63 s in and sets
  // off for "next" about 1.93 s before record.cjs calls "on-slide". The wait
  // between lasts as long as record.cjs takes to read the deck from the app
  // (0.6 s in the take, 1.7 s in the deck end filmed again at 14:43). Of a
  // longer wait 0.57 s are kept; the join lies inside the still picture.
  const DECK_REST_KEPT_TO = 1.2, DECK_SETS_OFF = 1.98;
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
  // Typing, a key every `pace` seconds: `keys` are the seconds of the stretch
  // at which each key was pressed.
  const typing = (stretch, keys, pace) => play(stretch, 0, 0, keys.length * pace, { src: keys.map((k, i) => ({ t: i * pace, v: k + 0.02 })) });

  // ---- 1  the request -----------------------------------------------------------
  const keys = footage.keys('review');
  part('ask-review', keys[0] - 0.8, keys[0]);                      // the pointer goes to the box
  typing('ask-review', keys, KEY);
  part('ask-review', keys[keys.length - 1] + 0.02, len('ask-review'));   // read, then sent
  start('ack', 1.0, { dissolve: true });                           // the first words of the assistant

  // ---- 2  the agents come up, and the way into the Agentic IDE ---------------------
  part('agents-in', len('agents-in') - 1.9, AGENT_TO, { dissolve: true });   // their lines, the pointer to the first
  part('to-ide', IDE_FROM, IDE_TO);                                // the click: its thread opens

  // ---- 3  two more of them beside it, and all three at work ------------------------
  whole('beside-1');                                               // "Open side by side" from a thread's menu
  whole('beside-2');                                               // and once more: three columns
  part('watching', WATCH_FROM, footage.rest('watching', 2.2));
  // The wait for the last of them left out: the finished reviews.
  part('done', DONE_FROM, DONE_TO, { dissolve: true });

  // ---- 4  back to the assistant: the card of the deck and its answer ---------------
  whole('to-chat');
  whole('answer', { dissolve: true });

  // ---- 5  the deck, a slide on, and its title changed by hand -----------------------
  whole('open-deck');
  const hand = footage.keys('title', 'deck');
  // After the slide turns, nothing moves for 0.9 s until record.cjs calls
  // "on-slide" and the pointer sets off for the title: half of that is kept,
  // the join lies inside the still picture.
  const onSlide = footage.at('on-slide', 'deck');
  const turned = onSlide > 1 && onSlide < hand[0];
  const setsOff = onSlide - DECK_SETS_OFF;
  const waited = turned && setsOff - DECK_REST_KEPT_TO > 0.3;
  if (turned) {
    if (waited) part('deck', 0, DECK_REST_KEPT_TO);                // the deck, the pointer over it
    part('deck', waited ? setsOff : 0, onSlide - 0.47);            // a slide on
    part('deck', onSlide - 0.02, hand[0]);                         // into its title, all of it selected
  } else {
    part('deck', 0, hand[0]);
  }
  typing('deck', hand, HAND);
  part('deck', hand[hand.length - 1] + 0.02, len('deck'));         // saved, then Present
  // A take put together from two filmings of the same end (a merged take.json)
  // may go on in a stretch called "present", from a moment at which both show
  // the same picture: the slide in Present, the pointer at rest.
  whole('present');

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
