// The README video's cut: which footage is on screen when, where the picture
// moves in, and the few words above it. film.html draws it.
//
// Times are bars and beats of the music (115 beats a minute, four to the bar),
// so every cut falls on a beat. Footage is named by the stretches record.cjs
// filmed; a place in the window is a mark of record.cjs or plain window
// pixels (the window is 1200 x 675).
window.EDIT = (footage) => {
  const BEAT = 60 / 115.02, FIRST = 0.174;      // the music's pulse, and its first beat
  const bar = (n, beat = 0) => FIRST + (n * 4 + beat) * BEAT;
  const W = footage.WIN.width, H = footage.WIN.height;
  const FULL = [0, 0, W, H];
  const INK = '#0A0A0A', PAPER = '#F7F7F4', SOFT = '#8B8A84';

  // The part of the window around `box` that has the shape w : h.
  const around = (box, aspect, pad = 0) => {
    let w = box.width + 2 * pad, h = box.height + 2 * pad;
    if (w / h < aspect) w = h * aspect; else h = w / aspect;
    if (w > W) { w = W; h = w / aspect; }
    if (h > H) { h = H; w = h * aspect; }
    const x = Math.min(W - w, Math.max(0, box.x + box.width / 2 - w / 2));
    const y = Math.min(H - h, Math.max(0, box.y + box.height / 2 - h / 2));
    return [x, y, w, h];
  };
  const box = (name, fallback) => footage.mark(name) || { x: fallback[0], y: fallback[1], width: fallback[2], height: fallback[3] };
  const len = (name) => footage.length(name);

  const shots = [], captions = [], titles = [];
  // Footage `stretch` from t0 to t1. `src` is where in the stretch the film
  // is (seconds, as keyframes), `cam` the part of the window shown, `card`
  // where on the stage it stands: centre and width. A keyframe's `t` is a
  // share of the shot (0 to 1).
  const shot = (stretch, t0, t1, o) => {
    if (!footage.has(stretch)) return;
    const keys = (list) => list.map((k) => ({ ...k, t: k.t * (t1 - t0) }));
    shots.push({
      stretch, t0, t1,
      src: keys(o.src).map((k) => ({ ease: 'linear', ...k })),
      cam: keys(o.cam || [{ t: 0, v: FULL }]),
      card: keys(o.card || [{ t: 0, v: WIDE }]),
      enter: o.enter, exit: o.exit, radius: o.radius,
    });
  };
  const say = (text, t0, t1, o = {}) => captions.push({ text, t0, t1, ...o });
  const WIDE = [960, 612, 1440];            // the whole window under a caption
  const IN = { kind: 'rise', dur: 0.6 }, OUT = { kind: 'sink', dur: 0.22 }, POP = { kind: 'pop', dur: 0.4 };

  // The places the picture moves in on.
  const typed = box('composer-typed', [143, 539, 654, 108]);
  const stage = box('stage', [77, 33, 787, 643]);
  const CHAT = around({ x: stage.x, y: 150, width: stage.width, height: H - 150 }, 1.5);   // the conversation's newer end
  const CHAT_CARD = [960, 618, 1180];
  const link = box('agent-link', [218, 390, 247, 23]);
  const input = box('thread-input', [340, 494, 766, 84]);
  const THREAD = around({ x: input.x - 34, y: 36, width: input.width + 68, height: 470 }, 16 / 9);
  const CLOSE = [960, 618, 1500];           // a part of the window, larger than life

  // ---- 0  the name ----------------------------------------------------------
  titles.push({
    t0: 0, t1: bar(2), out: 0.28,
    parts: [
      { kind: 'mark', at: -0.5, size: 300, y: 400, color: INK },   // there in the first frame: a player shows it as the still
      { kind: 'name', at: bar(0, 2), text: 'Dodaios', size: 148, y: 590, color: INK },
      { kind: 'line', at: bar(1), text: 'Your super agent.', size: 58, y: 782, color: SOFT },
    ],
  });

  // ---- 1  the request, typed -------------------------------------------------
  const TYPE = around(typed, 3.5, 22), TYPE_CARD = [960, 620, 1560];
  const typedAt = footage.markAt('composer-typed', 'ask');
  shot('ask', bar(2), bar(5), {
    src: [{ t: 0, v: 1.0 }, { t: 0.72, v: typedAt + 0.25 }, { t: 1, v: len('ask') }],
    cam: [{ t: 0, v: TYPE }, { t: 0.74, v: TYPE }, { t: 1, v: CHAT }],
    card: [{ t: 0, v: TYPE_CARD }, { t: 0.74, v: TYPE_CARD }, { t: 1, v: CHAT_CARD }],
    enter: IN,
  });
  say('Tell it what you need.', bar(2), bar(5) - 0.12);

  // ---- 2  Dodaios looks into it and briefs the agents ------------------------
  // Two pieces of the window side by side: the conversation, and the panel
  // that says what Dodaios is doing. The wait in the middle passes quickly;
  // its answer comes in at its own speed.
  const answered = len('answer');
  const pace = [{ t: 0, v: 0 }, { t: 0.1, v: 6.5 }, { t: 0.36, v: 9.5 }, { t: 0.56, v: answered - 2.6 }, { t: 1, v: answered }];
  const panel = box('panel', [864, 33, 336, 643]);
  const PANEL = [panel.x + 4, panel.y + 4, panel.width - 8, 372];
  const CHAT_LEFT = [715, 618, 1000], PANEL_RIGHT = [1485, 618, 440];
  shot('answer', bar(5), bar(8), {
    src: pace,
    cam: [{ t: 0, v: CHAT }],
    card: [{ t: 0, v: CHAT_CARD }, { t: 0.11, v: CHAT_LEFT }],
  });
  shot('answer', bar(5) + 0.18, bar(8), {
    src: pace.map((k) => ({ ...k, v: k.v + 0.18 * (k.t < 0.2 ? 6 : 1) })),
    cam: [{ t: 0, v: PANEL }],
    card: [{ t: 0, v: PANEL_RIGHT }],
    enter: IN, exit: { kind: 'right', dur: 0.24 },
  });
  say('Dodaios finds the cause.', bar(5), bar(8) - 0.12);
  // The agents are named in its message: in on the names, and the click on one.
  const LINK = around({ x: link.x - 50, y: link.y - 22, width: 560, height: 90 }, 2.7, 24);
  const started = len('started');
  shot('started', bar(8), bar(9), {
    // It ends on the click: the half second in which the IDE loads is left out.
    src: [{ t: 0, v: 0.1 }, { t: 1, v: started - 0.5 }],
    cam: [{ t: 0, v: CHAT }, { t: 0.36, v: LINK }, { t: 0.8, v: LINK }, { t: 1, v: FULL }],
    card: [{ t: 0, v: CHAT_LEFT }, { t: 0.36, v: CLOSE }, { t: 0.8, v: CLOSE }, { t: 1, v: WIDE }],
  });
  say('Then it puts coding agents on it.', bar(8), bar(11) - 0.12);

  // ---- 3  the Agentic IDE: the agents at work --------------------------------
  shot('thread', bar(9), bar(11), {
    src: [{ t: 0, v: 0 }, { t: 1, v: len('thread') }],
    cam: [{ t: 0, v: FULL }, { t: 0.45, v: FULL }, { t: 0.85, v: THREAD }],
  });
  shot('thread-ledger', bar(11), bar(13), {
    src: [{ t: 0, v: 1.2 }, { t: 1, v: len('thread-ledger') }],
    cam: [{ t: 0, v: THREAD }],
  });
  say('Watch them work in the Agentic IDE.', bar(11), bar(13) - 0.12);
  shot('thread-trailhead', bar(13), bar(15), {
    src: [{ t: 0, v: 0 }, { t: 1, v: Math.min(len('thread-trailhead'), 5.2) }],
    cam: [{ t: 0, v: THREAD }, { t: 0.2, v: FULL }, { t: 0.5, v: FULL }, { t: 0.8, v: THREAD }],
  });
  say('Two agents. Two projects. At once.', bar(13), bar(15) - 0.12);

  // ---- 4  the change, reviewed -------------------------------------------------
  const review = box('review-ledger', [16, 41, 1168, 594]);
  const DIFF = around({ x: review.x + 270, y: review.y + 80, width: review.width - 280, height: 500 }, 16 / 9);
  const reviewAt = footage.markAt('review-ledger', 'review-ledger');
  shot('review-ledger', bar(15), bar(17), {
    src: [{ t: 0, v: reviewAt - 0.5 }, { t: 1, v: Math.min(len('review-ledger') - 1.4, reviewAt + 6.8) }],
    cam: [{ t: 0, v: FULL }, { t: 0.28, v: FULL }, { t: 0.6, v: DIFF }],
    card: [{ t: 0, v: WIDE }, { t: 0.28, v: WIDE }, { t: 0.6, v: CLOSE }],
    exit: OUT,
  });
  say('Review every change.', bar(15), bar(17) - 0.12);

  // ---- 5  Dodaios checks and reports -----------------------------------------
  const REPORT = around({ x: stage.x + 88, y: stage.y + 3, width: 570, height: 228 }, 2.5);
  shot('report', bar(17), bar(19), {
    src: [{ t: 0, v: 0.3 }, { t: 1, v: len('report') }],
    cam: [{ t: 0, v: CHAT }, { t: 0.25, v: CHAT }, { t: 0.6, v: REPORT }],
    card: [{ t: 0, v: CHAT_CARD }, { t: 0.25, v: CHAT_CARD }, { t: 0.6, v: CLOSE }],
    enter: IN, exit: OUT,
  });
  say('Dodaios checks the result itself.', bar(17), bar(19) - 0.12);

  // ---- 6  the artifact ----------------------------------------------------------
  const typed2 = { x: typed.x, y: typed.y + 20, width: typed.width, height: typed.height - 20 };
  shot('ask-artifact', bar(19), bar(20), {
    src: [{ t: 0, v: 1.0 }, { t: 1, v: len('ask-artifact') - 0.6 }],
    cam: [{ t: 0, v: around(typed2, 3.5, 22) }],
    card: [{ t: 0, v: TYPE_CARD }],
    enter: IN, exit: OUT,
  });
  const page = box('artifact', [77, 100, 1123, 545]);
  const PAGE = around({ x: page.x, y: 36, width: page.width, height: H - 36 }, 16 / 9);
  shot('artifact', bar(20), bar(22), {
    src: [{ t: 0, v: 0.3 }, { t: 1, v: len('artifact') - 0.3 }],
    cam: [{ t: 0, v: FULL }, { t: 0.2, v: FULL }, { t: 0.6, v: PAGE }],
    enter: POP, exit: OUT,
  });
  say('And builds what you want to see.', bar(19), bar(22) - 0.12);

  // ---- 7  four more things, two beats each ---------------------------------------
  const picker = box('model-picker', [401, 268, 310, 304]);
  const more = [
    ['tour-plugins', 'Plugins.', 1.0, [290, 80, 900, 506]],
    ['tour-memory', 'Memory.', 1.9, [215, 60, 975, 548]],
    ['tour-models', 'Any\u00a0model.', 1.5, around({ x: picker.x - 70, y: picker.y - 30, width: 640, height: 400 }, 16 / 9)],
    ['tour-pets', 'A\u00a0pet.', 0.6, [262, 262, 720, 405]],
  ];
  more.forEach(([name, , from, view], i) => {
    // Each stays until the next one covers it.
    shot(name, bar(22, i * 2), bar(22, i * 2 + 2) + (i + 1 < more.length ? 0.14 : 0), {
      src: [{ t: 0, v: from }, { t: 1, v: Math.min(len(name), from + 2 * BEAT * 1.5) }],
      cam: [{ t: 0, v: view }],
      enter: { kind: 'pop', dur: 0.3 },
    });
  });
  say(more.map(([, word]) => word).join(' '), bar(22), bar(24) - 0.1, { times: more.map((_, i) => bar(22, i * 2)) });

  // ---- 8  what it is, then the name again, on black ---------------------------
  const END = bar(24), HIT = bar(25);
  titles.push({
    t0: END, t1: HIT + 0.05, out: 0.22,
    parts: [{ kind: 'name', at: 0.12, text: 'Turn your computer into an AI agent.', size: 76, y: 492, color: PAPER, step: 0.09 }],
  });
  titles.push({
    t0: HIT, t1: 60,
    parts: [
      { kind: 'mark', at: 0, size: 260, y: 395, color: PAPER },
      { kind: 'name', at: 0.06, text: 'Dodaios', size: 124, y: 560, color: PAPER },
      { kind: 'line', at: 2 * BEAT, text: 'Open source. Runs on your computer.', size: 44, y: 740, color: '#C9C8C2' },
      { kind: 'mono', at: 3 * BEAT, text: 'github.com/Dodaios/Dodaios', size: 30, y: 838, color: SOFT },
    ],
  });

  return {
    duration: 55.3,
    dark: [{ t: 0, v: 0 }, { t: END - 0.2, v: 0 }, { t: END + 0.12, v: 1, ease: 'linear' }],
    shots, captions, titles,
  };
};
