// The cut of the hero clip (the recording at the top of the README), from the
// "onehero" part of clip-hero-record.cjs: one short request to the assistant
// hands real coding work to one coding agent. The request is typed, Nova
// answers and the agent's chip comes into the answer, one click opens the
// agent's thread in the Agentic IDE where it edits and runs the tests, and
// back in the chat Nova reports the result.
// clip-hero-render.cjs loads it with FILM_EDIT=clip-hero-edit-hero.js.
//
// The rules of a README recording: the take in its own order, nothing laid
// over it, every shot at the speed it was filmed at. A wait for a model is
// left out with a short dissolve; typing plays at an even person's pace.
// The seconds below are those of the take of 16 November 2026 (take5); a new
// take needs its own (look at a contact sheet of the stretches first).
window.EDIT = (footage) => {
  const W = footage.WIN.width;
  const FULL = [0, 0, W];
  const KEY = 0.03;                 // seconds a typed key of the request
  const DISSOLVE = 0.3;
  // "ack": Nova's first words stream in during the first second.
  const ACK_TO = 1.05;
  // "agent-in": the chip is in the answer; the pointer goes to it and rests.
  // "to-ide": the click at 0.09 s, the thread opens at 0.88 s.
  const IDE_TO = 1.6;
  // "thread": the agent edits README.md, runs the tests: "All 12 tests pass"
  // comes in at 111.1 s.
  const WORK_FROM = 110.55, WORK_TO = 113.0;
  // "to-chat": the pointer goes to the Dodaios switch, clicks (1.0 s), the chat shows.
  const CHAT_FROM = 0.3;
  // "report": Nova's report comes in at 4.19 s and has settled by 4.9 s; its
  // next message comes at 8.97 s, so the shot ends before that.
  const REPORT_FROM = 3.95, REPORT_TO = 6.85;
  const len = (name) => footage.length(name);

  const shots = [];
  let t = 0;
  const play = (stretch, from, to, seconds, o = {}) => {
    if (!footage.has(stretch) || seconds <= 0) return;
    const src = o.src || [{ t: 0, v: Math.max(0, from) }, { t: seconds, v: to }];
    if (o.dissolve && shots.length) shots[shots.length - 1].t1 += DISSOLVE;
    shots.push({ stretch, t0: t, t1: t + seconds, src, cam: [{ t: 0, v: FULL }], fade: o.dissolve ? DISSOLVE : 0 });
    t += seconds;
  };
  const part = (stretch, from, to, o) => {
    const a = Math.max(0, from), b = Math.min(len(stretch), to);
    play(stretch, a, b, b - a, o);
  };
  const typing = (stretch, keys, pace) => play(stretch, 0, 0, keys.length * pace, { src: keys.map((k, i) => ({ t: i * pace, v: k + 0.02 })) });
  const still = (stretch, at, seconds) => {
    shots[shots.length - 1].t1 += seconds;
    shots.push({ stretch, t0: t, t1: t + seconds, src: [{ t: 0, v: at }], cam: [{ t: 0, v: FULL }], fade: seconds });
    t += seconds;
  };

  // 1  the request
  const keys = footage.keys('hero');
  const sent = footage.at('sent-hero', 'ask-hero');
  part('ask-hero', keys[0] - 0.6, keys[0]);
  typing('ask-hero', keys, KEY);
  part('ask-hero', keys[keys.length - 1] + 0.02, sent + 0.35);
  // 2  Nova answers; the agent's chip, one click into its thread
  part('ack', 0, ACK_TO, { dissolve: true });
  part('agent-in', 0, len('agent-in'), { dissolve: true });
  part('to-ide', 0, IDE_TO);
  // 3  the agent at work: an edit, the tests pass
  part('thread', WORK_FROM, WORK_TO, { dissolve: true });
  // 4  back in the chat: Nova reports
  part('to-chat', CHAT_FROM, len('to-chat'), { dissolve: true });
  part('report', REPORT_FROM, REPORT_TO, { dissolve: true });
  // back into the first picture, so the loop has no jump
  still(shots[0].stretch, shots[0].src[0].v, DISSOLVE);

  return { duration: t, stretch: 1, black: [{ t: 0, v: 0 }, { t, v: 0 }], shots };
};
