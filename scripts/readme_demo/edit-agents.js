// The cut of the agents clip, the recording beside "Every coding agent, side
// by side" in the README: in the Agentic IDE two more coding agents' threads
// are opened beside the first, each from a thread's menu, until three work
// side by side on real pull requests; the first of them lands its review; then
// the picker of a thread lists the coding agents down its side and the models
// of each.
// It is cut from the same take as the hero clip: stretches of the "hero" part
// of record.cjs, and the "picker" stretch filmed before it.
// film.html draws it; render.cjs loads it with FILM_EDIT=edit-agents.js.
//
// The rules of a README recording: nothing laid over the picture, and the
// footage plays at the speed it was filmed at. The clip is made of the
// moments in which the picture itself changes (a column opens, a review
// arrives, the picker shows another agent's models), not of three columns
// standing still while the agents think: a wait for the agents is left out
// with a short dissolve. It ends on a dissolve into its own first picture, so
// it loops in the README without a jump.
// The seconds below are those of the take of 15 November 2026; a new take
// needs its own (look at a contact sheet of the stretches first).
window.EDIT = (footage) => {
  const W = footage.WIN.width;
  const FULL = [0, 0, W];           // the part of the window shown: left, top, width
  const DISSOLVE = 0.3;
  // "beside-1": the pointer sets off at once for a thread's row, opens its
  // menu, and the second column opens (1.0 to 2.5 s); at 3.55 s the pointer
  // rests in it, where "beside-2" begins.
  const BESIDE_1_TO = 3.6;
  // "beside-2": the same once more, the third column opens at 2.5 to 3.0 s;
  // at 3.95 s the pointer rests in it.
  const BESIDE_2_TO = 4.05;
  // "watching": at about 8.5 s the first agent's review arrives in its column,
  // at 9.15 s its stop button turns into the send button (it has finished),
  // and the pointer comes to rest at the moment record.cjs calls "rest".
  const REVIEW_FROM = 8.1, REVIEW_TO = 9.6;
  // "picker": the pointer sets off for the agent and model control at about
  // 0.45 s; Claude Code is chosen again at about 5.25 s and its models show.
  const PICK_FROM = 0.4, PICK_TO = 5.6;
  const len = (name) => footage.length(name);

  const shots = [];
  let t = 0;
  // `stretch` from second `from` to second `to`, at the speed it was filmed at.
  const part = (stretch, from, to, o = {}) => {
    const a = Math.max(0, from), b = Math.min(len(stretch), to);
    if (!footage.has(stretch) || b <= a) return;
    // The shot before stays under a dissolve until it is over.
    if (o.dissolve && shots.length) shots[shots.length - 1].t1 += DISSOLVE;
    shots.push({ stretch, t0: t, t1: t + b - a, src: [{ t: 0, v: a }, { t: b - a, v: b }], cam: [{ t: 0, v: FULL }], fade: o.dissolve ? DISSOLVE : 0 });
    t += b - a;
  };
  // One picture of `stretch`, faded in over the last shot: the end of the loop.
  const still = (stretch, at, seconds) => {
    shots[shots.length - 1].t1 += seconds;
    shots.push({ stretch, t0: t, t1: t + seconds, src: [{ t: 0, v: at }], cam: [{ t: 0, v: FULL }], fade: seconds });
    t += seconds;
  };

  // ---- 1  two more threads opened beside the first: three columns -------------------
  part('beside-1', 0, BESIDE_1_TO);
  part('beside-2', 0, BESIDE_2_TO);          // joins where the pointer rests: no cut to see

  // ---- 2  the wait for the agents left out: the first review arrives ------------------
  part('watching', REVIEW_FROM, footage.rest('watching', REVIEW_TO), { dissolve: true });

  // ---- 3  the picker: the coding agents down its side, the models of each -----------
  part('picker', PICK_FROM, PICK_TO, { dissolve: true });

  // ---- 4  back into the first picture, so that the loop has no seam -----------------
  if (shots.length) still(shots[0].stretch, shots[0].src[0].v, DISSOLVE);

  return {
    duration: t,
    stretch: 1,
    black: [{ t: 0, v: 0 }, { t: t, v: 0 }],
    shots,
  };
};
