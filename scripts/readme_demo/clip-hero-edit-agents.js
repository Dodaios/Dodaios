// The cut of the agents clip ("Your coding agents, side by side" in the
// README), from the "agents" part of clip-hero-record.cjs: three Claude Code
// threads on Claude Sonnet 5, started by hand in the Agentic IDE on three small
// tasks in the two sample projects. The third column opens beside the other
// two, the middle agent finishes (its tests pass, the card of its edited
// files comes in), and the agent and model picker of a thread shows the other
// coding agents down its side.
// clip-hero-render.cjs loads it with FILM_EDIT=clip-hero-edit-agents.js.
// Footage plays at the speed it was filmed at; a wait for the agents is left
// out with a short dissolve, and the clip dissolves into its own first
// picture at the end, so it loops without a jump. The seconds below are those
// of the take of 16 November 2026 (take1).
window.EDIT = (footage) => {
  const W = footage.WIN.width;
  const FULL = [0, 0, W];
  const DISSOLVE = 0.3;
  // "beside-2": the third thread is opened from its row's menu; its column
  // opens at 3.03 s and the pointer rests in it by about 3.95 s.
  const BESIDE_TO = 4.0;
  // "watching": the middle agent's report comes in from 7.2 s ("All 7 tests
  // pass"), then the card of its two edited files; done by 10.4 s.
  const DONE_FROM = 7.0, DONE_TO = 10.6;
  // "picker": the control is clicked and the picker opens at 1.65 s; Codex is
  // chosen in the rail at about 3.7 s and its models show.
  const PICK_FROM = 1.0, PICK_TO = 4.75;
  const len = (name) => footage.length(name);
  const shots = [];
  let t = 0;
  const part = (stretch, from, to, o = {}) => {
    const a = Math.max(0, from), b = Math.min(len(stretch), to);
    if (!footage.has(stretch) || b <= a) return;
    if (o.dissolve && shots.length) shots[shots.length - 1].t1 += DISSOLVE;
    shots.push({ stretch, t0: t, t1: t + b - a, src: [{ t: 0, v: a }, { t: b - a, v: b }], cam: [{ t: 0, v: FULL }], fade: o.dissolve ? DISSOLVE : 0 });
    t += b - a;
  };
  const still = (stretch, at, seconds) => {
    shots[shots.length - 1].t1 += seconds;
    shots.push({ stretch, t0: t, t1: t + seconds, src: [{ t: 0, v: at }], cam: [{ t: 0, v: FULL }], fade: seconds });
    t += seconds;
  };
  part('beside-2', 0, BESIDE_TO);
  part('watching', DONE_FROM, DONE_TO, { dissolve: true });
  part('picker', PICK_FROM, PICK_TO, { dissolve: true });
  still(shots[0].stretch, shots[0].src[0].v, DISSOLVE);
  return { duration: t, stretch: 1, black: [{ t: 0, v: 0 }, { t, v: 0 }], shots };
};
