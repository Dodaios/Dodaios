# Verse on Unreal: orchestration

How the Unreal Verse gets built by many agents at once: phases and their
gates, the rules every parallel agent follows, the machine limits, the
verification recipe for Unreal changes, and the prompt template for a
sub-task agent. Builds on `README.md` (decisions), `architecture.md`
(modules, lanes, lock) and `contracts/`. The packages themselves are in
`work-packages.md`; this file never redefines their scope.

## 1. Roles

| Role | Count | Owns | Never does |
|---|---|---|---|
| Orchestrator | 1 | Phase plan, scheduling, the sub-task queue, gate verdicts | Writes product code |
| Integration owner | 1 (one session at a time, handed over in writing) | `docs/verse/unreal/contracts/**`, `unreal/Verse/Source/VerseCore/**`, `unreal/Verse/Source/Verse/**` (primary module), every `*.Build.cs` and `*.Target.cs`, `unreal/Verse/Verse.uproject`, `unreal/Verse/Config/**`, every `.gitattributes`, `.gitignore` and `.lfsconfig`, `.githooks/**`, levels and data layers, the LFS locks of shared assets (master materials are authored by WP14, rig and physics assets by WP13; the integration owner takes the lock and merges), `scripts/unreal/**` except the scripts a package owns in `work-packages.md` (WP10, WP22), the G0.11 fake bridge and golden fixtures, screenshot ground truth, and the G0 workflows until G0.10 hands them to WP10 | Lands a contract change without its contract tests |
| Package lead | 1 per package (22) | The package's owned paths and acceptance list in `work-packages.md`; assigns the sub-tasks listed there (`WP<nn>.<k>`) and may split one further into `WP<nn>.<k>a`, `b`, each with a subset of its paths | Touches another package's paths |
| Sub-task agent | Many per package | One sub-task: a subset of its package's owned paths | Edits outside its assigned paths, changes a contract, merges by hand |
| Verifier | 1 per sub-task PR, fresh context | An adversarial check of one PR (section 5.4) | Pushes to the branch it verifies |

## 2. Phases and gates

Phases run strictly in order. A gate is a checklist the orchestrator
evaluates from evidence (CI runs, reports, screenshots), never from an
agent's own claim. A failed gate item reopens the work that owns it; the
next phase does not start early "for the parts that are ready".

### Phase 0: foundation (serial, integration owner plus a few agents)

The steps below produce the G0 items of `work-packages.md` section 1; the
column "G0 items" maps them.

| Step | Output | G0 items | Notes |
|---|---|---|---|
| 0.1 Toolchain | Visual Studio 2022 Build Tools with the MSVC and Windows SDK versions 5.7 requires; the engine's Linux cross-compile toolchain, `LINUX_MULTIARCH_ROOT`; git-lfs; `unreal/Toolchain/toolchains.json` pinning all versions; `scripts/unreal/doctor.py` that checks them | G0.1 | The installers need an elevated, one-time install the person approves. Nothing in phase 0 after 0.1 starts before `doctor.py` is green |
| 0.2 Project skeleton | `unreal/Verse/Verse.uproject` pinned to 5.7.1; the primary module plus the 13 feature modules, each compiling empty; `VerseServer.Target.cs` deleted, `VerseHarness` only in the Editor target; plugins per architecture §2 rule 4; World Partition with One File Per Actor; one empty map per deck; the nested `unreal/Verse/.gitattributes` and `.gitignore` and the other repo changes of architecture §8.4 | G0.4, G0.5, G0.8, G0.12 | Every module ships a `Verse.<Module>.Smoke` automation test that passes |
| 0.3 Contracts frozen | Every file in `contracts/` moves to "Status: frozen v1". Each one becomes code: shared types, enums, interfaces and DataAsset schemas in `VerseCore`; a null implementation (stub) of every interface so any package can build and test against it; golden data files (`space_vectors.json`, bridge schema JSON, penetration table) | G0.2, G0.3, G0.9, G0.11 | A contract is frozen only when its contract tests exist and pass |
| 0.4 Contract tests | `Verse.Contract.*` automation tests (coordinates round trip, enum order, struct sizes and field order of replicated types, bridge codec against the JSON schemas, interface stubs answer as specified); pytest on the backend side of `verse.bridge/1` against the same schema files | G0.3, G0.11 | Both sides read the same files; no hand-copied numbers |
| 0.5 Scripts | `scripts/unreal/with_lock.py` (section 4), `build.py`, `test.py`, `smoke.py`, `screenshot.py`, `balance.py` (skeleton), `fake_bridge.py`, `worktree.py {new,remove}`, `doctor.py` | G0.6, G0.11 | Agents call these, never UBT, UAT or the editor directly |
| 0.6 Self-hosted runner | The runner, lanes `unreal-static` and `unreal-build` from architecture §8.3, wired into the one required check `CI gate` as jobs under `gate.needs` that pass without work when no Unreal path changed (architecture §8.2) | G0.10 | Fork PRs never reach the runner (architecture §8.2) |
| 0.7 Headless test runner | `test.py` runs automation under `-nullrhi` and fails on any failed, skipped-unexpectedly or crashed test; a Gauntlet skeleton runs two placeholder bots in an empty map for 60 s and exits cleanly | G0.6 | Measures headless speed (architecture risk RK1) |
| 0.8 Baselines | Measured on the reference box: clean and incremental editor build time, game build time, `Intermediate/` + `Binaries/` size of one worktree, warm DDC size, headless sim speed (x real time per process), RAM per headless process | G0.13 | These numbers replace the "start values" in section 4 in the same PR |
| 0.9 Pilot | One throwaway sub-task (a test-only change in `VerseCore`) goes the full path: worktree, PR, LFS push, queue, verifier, done gate | G0.13 | Proves the pipeline before 22 packages hit it |

**Gate G0** (all must hold):

| # | Check | Evidence |
|---|---|---|
| GC0.1 | `doctor.py` green on the dev box and the runner | Log in the gate issue |
| GC0.2 | `unreal-build` green on `main`: Win64 Development Editor, Win64 Development Game, Linux Development Game | CI run link |
| GC0.3 | All `Verse.Contract.*` and `Verse.*.Smoke` tests green under `-nullrhi`; backend contract pytest green, including the G0.11 golden fixtures | `index.json` report counts |
| GC0.4 | `unreal-static` green: DAG check, forbidden-name scan, LFS pointer check, size gate, licence ledger; the repo gates of architecture §8.4 green on the same PR (junk, language, design references, docs privacy) | CI run link |
| GC0.5 | Every contract file says "frozen v1" and names its tests | Grep in the gate issue |
| GC0.6 | The pilot reached `agent_done_gate.py` DONE, and a fresh clone of `main` with LFS on gets every object the pilot pushed | Gate output, clone log |
| GC0.7 | Section 4 limits replaced by measured values | The PR that did it |

Gate check ids carry the `GC` prefix so they never read as the G0 items of
`work-packages.md` section 1.

### Phase 1: fan-out (all 22 packages in parallel)

| Rule | Value |
|---|---|
| Start | All 22 package leads start together after G0. Each publishes its package's sub-tasks (`work-packages.md`; one sub-task = one PR, about a day of agent work at most) in the package's tracking issue with the owned paths per sub-task |
| Isolation | Packages code against the frozen contracts and the stubs of the other packages, never against another package's unfinished code. A package that needs behaviour another package has not landed tests against the stub |
| Dependencies | Inside a package, sub-tasks may depend on each other; across packages only via contracts. A cross-package need that the contract does not cover is a contract change request (section 3.4) |
| Art | Art sub-tasks follow `contracts/art-pipeline.md`: builders under `art/verse/`, export and import under the lock, placements only in the zone the sub-task owns |
| Cadence | The orchestrator keeps the sub-task queue full up to the session limit in section 4 and schedules builds so the lock stays busy but never deep (queue depth above 8 waiters: stop starting build-heavy sub-tasks) |

**Gate G1:**

| # | Check |
|---|---|
| GC1.1 | Every package's acceptance list in `work-packages.md` is green with its own tests, under `-nullrhi` where no GPU is needed and under the visual lane where it is |
| GC1.2 | No open contract change request; contract tests still green |
| GC1.3 | Every invariant named in `contracts/` (recoil R1-R6, gadgets GD1 to GD4, deathmatch D1-D6, destruction DR1-DR6, bot B1-B8, fairness F1-F7, L1, BR1) has a test, and the test is green or explicitly marked as needing integration (listed, not silent) |
| GC1.4 | `main` builds all three targets; no package still depends on a stub of its own interface |
| GC1.5 | Forbidden-name scan zero over `unreal/`, `art/verse/`, `docs/verse/`, commit messages and PR titles of the phase |

### Phase 2: integration and autonomous playtests

| Step | Output |
|---|---|
| 2.1 Wire up | The integration owner replaces stubs with the real implementations in the primary module's default classes, one package at a time, each its own PR, the full automation suite green after each |
| 2.2 Hangar arena | The day/arena switch, the arena zone, spawns, the armoury station, the in-Verse Verse bar quick start and the web launcher card quick start working end to end in a packaged build |
| 2.3 App link | `dodaios/verse_host/` against a real `Verse.exe`: launch, show, hide, dormant, crash restart, token, heartbeat, feeds, desk screens, takeover, Pixel Streaming panel. Checked in a dev instance of the app with synthetic data (section 5.6) |
| 2.4 Autonomous playtests | Gauntlet bot-vs-bot at scale per `contracts/bot.md` §11 (ladder, tricks, elite, fairness, learning, adaptive); netcode test with lagged clients; destruction scenarios (`wall_opened_unseen` and the destruction contract's set); a 2 h soak of endless deathmatch with destruction and repair |
| 2.5 Perf | Nightly `unreal-perf` fixed replay against architecture §7 budgets, with dictation running on the GPU for the VRAM check |
| 2.6 Person playtest | The person plays (README Testing) on a packaged build. Feedback becomes issues; the person-model refit from local duel telemetry (`contracts/bot.md` §11.2) runs after it |

**Gate G2:**

| # | Check |
|---|---|
| GC2.1 | All lanes (`unreal-static`, `unreal-build`, `unreal-gauntlet` long, `unreal-perf`) green on `main` three nights in a row |
| GC2.2 | Balance gates BG1-BG12 pass: no single trick beats hard; skilled model about 40 % vs elite inside the 95 % interval; fairness tests F1-F7 and L1 green |
| GC2.3 | Soak: zero crashes, zero ensures, no memory growth over 50 MB per hour, desync corrections within the netcode gate |
| GC2.4 | Every budget in architecture §7 met or a named exception the person accepted |
| GC2.5 | App-link matrix (2.3) green in the dev instance, with screenshots |
| GC2.6 | The person has played; each feedback item is fixed, or deferred by the person |

### Phase 3: parity, three.js deletion, release

| Step | Output |
|---|---|
| 3.1 Parity | Every line of `parity.md` checked with evidence (screenshot, test, or recorded run) against the Unreal Verse in the packaged build |
| 3.2 Deletion | One PR deletes the three.js Verse (`dodaios/ui/web/frontend/src/components/society/verse/**`, its tests, its public assets, its feeds that nothing else reads) and switches both mounts to the Unreal launcher and the Pixel Streaming panel. The frontend is rebuilt (`npm run build`) and the change is checked visible in the running desktop app |
| 3.3 Release | `unreal-package` for Win64 and Linux, IoStore chunks per deck, delta packages, the raised updater cap, signing through the existing workflow, installer smoke on a fresh sandbox, release cut from a commit |

**Gate G3:** parity checklist 100 % with evidence; deletion PR merged and
visible in the running app; release tag built and signed; installer smoke
green on Windows and Linux; no-GPU path shows "unsupported" and the rest of
the app works; `agent_done_gate.py` DONE for every branch of the phase.

## 3. Rules for parallel agents

### 3.1 Git

| Rule | Detail |
|---|---|
| One worktree per sub-task | `python scripts/unreal/worktree.py new wp<nn>-<k>-<slug>` runs `git fetch origin`, `git worktree add -b claude/verse-wp<nn>-<k>-<slug> C:/demo/wt/<short-id> origin/main` and `git config lfs.fetchexclude ""` in the new worktree. Worktree paths stay short (Unreal paths under `Intermediate/` hit the Windows path limit); `<short-id>` is at most 12 characters |
| Branch prefix | `claude/verse-wp<nn>-<k>-<slug>` for every sub-task (the pattern `validate_ownership` reads, `contracts/art-pipeline.md` 9); integration branches `claude/verse-int-<slug>` |
| Base | Always `origin/main`, never local `main` (a mirror, never committed on), never another agent's branch |
| Shared trees | Never `git stash` or `stash pop` in a tree another session may use; never touch the person's main checkout. Rebase only your own branch |
| Owned paths | Each sub-task's prompt lists its exact paths. A diff that touches anything else is refused by the verifier, whatever the reason. Generated files under `Saved/`, `Intermediate/`, `Binaries/` are never committed |
| Binary assets | `.uasset`/`.umap` only inside owned paths; One File Per Actor means each placed actor is its own file. Shared `lockable` assets need `git lfs lock` by the integration owner |
| Small PRs | One sub-task, one package, one topic. Target under 400 changed lines of hand-written code and under 30 binary files; split anything larger |
| Landing | `python scripts/agent_land.py` (rebase on latest main, static gates, reachable tests, `git lfs push` then push, PR labelled `auto-merge` for the merge queue). Then set the title with `gh pr edit <n> --title "type(verse): subject"` when the branch has more than one commit. After the merge bot pushes to the branch, `git fetch` before pushing again and re-request auto-merge. Never a manual merge, never a force-push to someone else's branch |
| Removing a worktree | 1. `python scripts/unreal/build.py clean` (deletes that worktree's `Binaries/`, `Intermediate/`, `Saved/`; never the shared DDC). 2. Unlink any `node_modules` junction first (`cmd /c rmdir <path>\node_modules`), never delete through it. 3. `git worktree remove <path>`. `worktree.py remove` does all three in this order |

### 3.2 Writing rules

English everywhere. Never name other games, studios, franchises or real
firearm makes or models: code, asset names, comments, commits, PR titles and
bodies, docs, test names. Weapons are fictional and modelled on no real
firearm. Assets are own work or CC0, recorded in `art/verse/LICENSES.md`.
The `unreal-static` forbidden-name scan enforces this; a hit blocks the PR.
No repo gate checks names in `.cpp`, `.h`, `.cs` or `.uasset` metadata, so
agents run `scripts/unreal/check_forbidden_names.py` on their diff before
each commit. The repo-wide rules (no `.fbx`, `.wav`, `.exr` or video, banned
folder names, English in `.ini` files, no user-profile paths in docs) are in
architecture §8.4.

### 3.3 Build discipline

| Rule | Detail |
|---|---|
| Wrapper only | Builds, cooks, commandlets, automation, screenshots, Blender exports and balance runs go through `scripts/unreal/*.py`, which take the lock (section 4) |
| Build when it pays | Write the whole change, then build once; fix compile errors in one more build. No build per edit |
| Targeted tests | Run your package's test filter (`Verse.<Module>.*`) plus `Verse.Contract.*`; the full suite runs in CI. Never run the repo's full Python suite locally (it dirties the worktree) |
| No GUI editor | Agents never open the interactive editor or any window on the person's desktop and never send input to the person's windows. Commandlets and `-unattended` only |
| Shared DDC | One local Zen DDC for the whole machine (`unreal/Toolchain/ddc.json`, 40 GB cap); every worktree and the runner use it. No per-worktree local DDC, no cloud DDC |

### 3.4 Contract changes

A contract is frozen at the start of phase 1. A sub-task agent that needs a
change writes a contract change request (CCR) as an issue labelled
`verse-contract`: the contract file and section, the change, why the frozen
version cannot work, every package it affects. It then stops that part of its
work (and continues the rest). Only the integration owner decides. An
accepted CCR lands as one PR by the integration owner that changes the
contract doc, the `VerseCore` types, the stubs, the contract tests and every
existing caller together, and bumps the contract's minor version. Packages
rebase after it lands. Tuning values marked "start value" are not contract
and change through the balance harness.

### 3.5 Done

A sub-task is done only when all of these hold, in this order:

1. **Build** green for the targets the change reaches (`build.py`).
2. **Tests** green: the package filter plus `Verse.Contract.*`, new tests for
   every new behaviour, and the visual lane when something visible changed.
3. **Adversarial verify** by a separate verifier agent (section 5.4): PASS.
4. **Evidence** in the PR body (section 5.5).
5. **`python scripts/agent_done_gate.py`** says DONE: PR merged through the
   queue, CI green on `main`, local `main` contains it.

## 4. Machine limits

Reference box: AMD Ryzen 7 7800X3D (8 cores, 16 threads), 32 GB RAM,
RTX 5070 Ti 16 GB, one drive `C:` (106 GB free on 2026-11-02, measured). The
GPU is shared with dictation, local models, Blender and WebView2; RAM is the
first limit for parallel compiles, VRAM for anything rendered, disk for
worktrees. These are start values; step 0.8 replaces them with measured ones.

| Limit | Value | Why |
|---|---|---|
| `gpu-heavy.lock` holders | **1** | Architecture §8.2: one compile, cook, package, commandlet, Blender export, rendered test or balance run at a time. Waiters queue in FIFO order, they never fail |
| UBT parallel actions inside a build | **10** (`-MaxParallelActions=10`) | About 1.5 GB RAM per compile action; leaves 6 threads and about 15 GB for the app, voice and agent sessions |
| Shader compile workers | **10** (`NumUnusedShaderCompilingThreads=6`, below-normal priority) | Same headroom as UBT |
| Headless (`-nullrhi`) processes inside one lock hold | **4** (`balance.py --jobs 4`, `test.py --jobs 4`) | About 2.5 GB RAM each; CPU-bound, no GPU |
| Rendered processes (screenshots, perf, packaged smoke with RHI) | **1**, Verse VRAM capped at 6 GB | Leaves 10 GB for dictation and local models |
| GPU perf captures | Nightly window only, skipped when the person used the machine in the last 5 min | Architecture §8.2 quiet hours |
| Running agent sessions on the box | **20** | About 0.4 GB each plus tools; together with one build stays under 32 GB |
| Worktrees holding Unreal build output | **12** | About 4 GB each for `Binaries/` + `Intermediate/` (to be measured); `build.py` refuses a new build below 40 GB free and asks the orchestrator to clean merged worktrees |
| Lock queue depth | Stop scheduling build-heavy sub-tasks above **8** waiters | Keeps an agent's wait for a build under about half an hour |

Hundreds of sub-tasks therefore run in waves of at most 20 sessions, and
builds are serial. Throughput is set by build time (step 0.8): with
incremental editor builds of a few minutes the box serves roughly 15-25
builds an hour, which is why agents build once per change (section 3.3).
Static checks and documentation-only work need no lock.

`with_lock.py` holds the lock as an OS file lock on
`C:/demo/.locks/gpu-heavy.lock` (released by the OS when the holder dies),
writes holder, command, start time and PID beside it for the queue view, and
times out a hold after 90 minutes with a loud log line, never by killing
other processes.

## 5. Verification recipe for Unreal changes

All commands run from the worktree root. `<UE>` is
`C:/Program Files/Epic Games/UE_5.7`; `<P>` is the absolute path of
`unreal/Verse/Verse.uproject` in the worktree. The scripts wrap exactly
these commands under the lock.

### 5.1 Build

```text
python scripts/unreal/build.py editor        # VerseEditor Win64 Development
python scripts/unreal/build.py game          # Verse Win64 Development
python scripts/unreal/build.py linux         # Verse Linux Development (cross)

# what build.py runs
"<UE>/Engine/Build/BatchFiles/Build.bat" VerseEditor Win64 Development -Project="<P>" -WaitMutex -NoHotReloadFromIDE -MaxParallelActions=10
```

Pass: exit code 0, no warning that the DAG check or `-WarningsAsErrors` for
`Verse*` modules turns into an error.

### 5.2 Headless automation tests

```text
python scripts/unreal/test.py "Verse.Combat+Verse.Contract"

# what test.py runs
"<UE>/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" "<P>" -ExecCmds="Automation RunTests Verse.Combat+Verse.Contract; Quit" -TestExit="Automation Test Queue Empty" -unattended -nullrhi -nosound -nosplash -NoP4 -stdout -FullStdOutLogOutput -ReportExportPath="<worktree>/unreal/Verse/Saved/Automation/<run>" -log="<run>.log"
```

| Topic | Rule |
|---|---|
| Names | `Verse.<Module>.<Area>.<Case>`; contract tests `Verse.Contract.*`; smoke `Verse.<Module>.Smoke`; visual `Verse.Visual.*` (5.3) |
| Kinds | Unit-style `IMPLEMENT_SIMPLE_AUTOMATION_TEST` for pure logic; latent tests with a world for gameplay; `AFunctionalTest` actors in the package's `/Game/Verse/Test/WP<nn>/` maps for scenarios; Gauntlet for multi-process (netcode, balance) |
| Pass | `test.py` parses `index.json`: zero failed, zero not-run among the requested tests, the requested filter matched at least one test, no `Fatal`, `Ensure` or crash in the log |
| Determinism | Tests seed `VerseCore` RNG; flaky is failed. A test that fails once in CI is quarantined only by the integration owner, with an issue |

Multi-process runs use the commands in `contracts/bot.md` §11.1 through
`balance.py` and the netcode test (dedicated server via the editor plus two
`-game -nullrhi` clients with `PktLag=60 PktLagVariance=10 PktLoss=1`).

### 5.3 Screenshot capture (anything visible)

```text
python scripts/unreal/screenshot.py --suite Verse.Visual.Hangar

# what screenshot.py runs (needs the GPU, under the lock)
"<UE>/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" "<P>" -game -d3d12 -windowed -ResX=1920 -ResY=1080 -ExecCmds="Automation RunTests Verse.Visual.Hangar; Quit" -TestExit="Automation Test Queue Empty" -unattended -nosound -benchmark -fps=30 -ReportExportPath="<run dir>"
```

| Topic | Rule |
|---|---|
| Shots | Visual tests place the camera at named bookmarks per deck and zone and call the automation screenshot function; the harness waits for shader compile and streaming to finish before each shot |
| Comparison | Against ground truth in `unreal/Verse/Tests/GroundTruth/Win64/` (never a folder named `Screenshots`, architecture §8.4), tolerance "low". A new or changed ground truth is approved only by the integration owner, after looking at it |
| Offscreen | The window is created off the person's monitors or minimised to them; agents never capture the person's desktop |
| Content | Visual tests run against `fake_bridge.py` with synthetic roster, pane and terminal data. No real terminal content, names or chats in any screenshot |
| Output | `Saved/Harness/proof/<branch>/` locally (never committed); in CI, a workflow artifact the PR body links |

### 5.4 Adversarial verify

A verifier agent with fresh context checks out the PR head in its own
worktree (read-only, never pushes) and gets the sub-task prompt, the diff and
the acceptance list. It must:

1. Confirm every changed path is in the sub-task's owned paths.
2. Rebuild and rerun the evidence commands itself; never trust pasted output.
3. Try to break the change: edge inputs, server vs client, `-nullrhi` vs
   rendered, destroyed or missing actors, contract invariants it touches.
   It writes at least one probing test; a probe that exposes a bug is handed
   to the author to keep.
4. Run the forbidden-name scan and the licence ledger check on the diff.
5. Answer `PASS` or `FAIL` with reproduction steps.

Two `FAIL` rounds on the same sub-task go to the package lead.

### 5.5 Evidence block (PR body)

```text
## Evidence
Sub-task: WP<nn>.<k>    Owned paths: <list>
Build: editor OK, game OK, linux OK|n/a        (build.py, <date>, <minutes>)
Tests: Verse.<Module>.* 41/41, Verse.Contract.* 18/18   report: <CI artifact link>
Visual: Verse.Visual.<Suite> 6/6 vs ground truth | n/a  screenshots: <artifact link>
Packaged smoke: OK | n/a
Verifier: PASS (<verifier session>), probes added: <test names>
Contract: unchanged | CCR #<n>
```

### 5.6 Packaged-build smoke test

For changes to startup, maps, packaging, the bridge, the window or anything
cooked, and nightly on `main`:

```text
python scripts/unreal/smoke.py

# what smoke.py runs
"<UE>/Engine/Build/BatchFiles/RunUAT.bat" BuildCookRun -project="<P>" -platform=Win64 -clientconfig=Development -build -cook -stage -pak -iostore -archive -archivedirectory="<worktree>/unreal/Verse/Saved/Smoke" -unattended -utf8output -nocompileeditor
python scripts/unreal/fake_bridge.py --token <random> &      # verse.bridge/1, synthetic data
DODAIOS_VERSE_TOKEN=<random> Saved/Smoke/Windows/Verse.exe -windowed -ResX=1280 -ResY=720 -VerseSmoke=boot,hangar,arena30s -log
```

Pass: first frame within 8 s; `hello`/`welcome` handshake and heartbeats on
the fake bridge; the hangar loads, switches to arena, 30 s of bot-vs-bot run;
`dormant`, `show` and `stop` commands behave as architecture §1.3 says; one
screenshot per stage; exit code 0; no `Fatal`, `Ensure` or crash in the log.
A `-nullrhi` variant of the same run covers the runner when the GPU is busy.
For app-link work (phase 2.3 on), the same build is launched by a dev
instance of the desktop app (its own port and data dir, never the person's
running app) through `POST /api/verse/launch`.

## 6. Sub-task agent prompt template

The package lead fills every `<...>`. A prompt missing any field is not sent.

```text
You are a sub-task agent for the Unreal Verse.

Read first, in order: docs/verse/unreal/README.md (binding decisions),
docs/verse/unreal/orchestration.md (these rules), your package in
docs/verse/unreal/work-packages.md (<WP-id>), and these contracts:
<contract files and sections>.

Goal: <one or two sentences: the outcome, not the implementation>.

Acceptance (all must be true and shown by tests):
- <criterion, with the test name that proves it>
- <criterion ...>

Owned paths (you may change only these):
- <path globs>
Read-only context: <paths worth reading>.
Stubs you code against: <interfaces from other packages>.

Setup: python scripts/unreal/worktree.py new wp<nn>-<k>-<slug>
Work only in that worktree, on branch claude/verse-wp<nn>-<k>-<slug> off origin/main.

Rules:
- English only. Never name other games, studios, franchises or real firearm
  makes or models anywhere, including commits and PR text.
- Own or CC0 assets only, recorded in art/verse/LICENSES.md.
- Builds, tests, cooks and screenshots only through scripts/unreal/*.py (they
  take the machine lock). Build once per change, not per edit.
- No interactive editor, no input to the person's windows, no git stash.
- Repo gates (architecture §8.4): never commit .fbx, .wav, .exr or video;
  no folder named Build, Models, Env, Logs, Dist, Video, Renders, Evidence,
  Recordings or Screenshots; no user-profile paths in docs; run
  scripts/unreal/check_forbidden_names.py on the diff before each commit.
- PR title: type(verse): subject, lower case, imperative.
- Need a contract change? Open a verse-contract issue (orchestration §3.4),
  stop that part, continue the rest.

Verify: build.py <targets>; test.py "<filters>+Verse.Contract";
<screenshot.py --suite ... | smoke.py | none>.
Land: python scripts/agent_land.py, with the evidence block (§5.5) in the PR.
Done when: a verifier answered PASS and python scripts/agent_done_gate.py
says DONE. Then remove the worktree with worktree.py remove.

Return: PR link, test counts, verifier verdict, open issues you created.
```
