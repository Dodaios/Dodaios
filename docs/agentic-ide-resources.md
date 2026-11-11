# Agentic IDE: the resource view

The **Resources** tab of the IDE's side panel answers one question: who is
using this computer right now. It shows processor, memory and graphics load,
and splits each of them by owner.

## What it shows

| Part | Meaning |
|------|---------|
| Three meters | Processor, memory and graphics card for the whole machine. Choosing one turns the chart, the bars and the order of the list to that metric. |
| Chart | The last five minutes, stacked by owner. The scale is always the whole machine, so the space above the stack is the headroom. |
| Coding agents | One row per pane, per thread, and per coding CLI found running anywhere else on the machine. |
| Inside an agent | The CLI itself, then every tool it started: an MCP server, a test run, a build, a browser, a shell. The same tool started several times is one line. |
| Connected apps | A program outside the agent's own processes that holds a local connection to one of its tools: a 3D editor behind its MCP server, a browser showing its dev server. Its load is shown beside the agent and is not added to the agent's total. |
| This app | The window, the core and the helper processes. |
| Everything else | The system and every other program: the remainder of the machine's own figure, so the parts add up to the meters. |

A tool an agent started can be ended from its row. Nothing else can: the
server accepts only handles it gave out with the last reading, and checks that
the process behind a handle is still the one it measured.

## How it measures

- `dodaios/core/process_snapshot.py` reads every process in one call. On
  Windows that is the system's own process table; elsewhere `psutil`.
- `dodaios/agentic_ide/resource_usage.py` sorts the processes into owners. It
  is pure: rows in, rows out. No command line leaves it, only a short label
  derived from one.
- `dodaios/agentic_ide/resource_sampler.py` turns two readings into rates and
  keeps the history. It measures **only when asked**. A closed tab costs
  nothing.
- `dodaios/hardware/gpu_usage.py` reads the graphics card.
- `GET /api/agentic-ide/resources` returns one reading with its history;
  `POST /api/agentic-ide/resources/end` ends tools.

Panes and threads are named because the app knows which process it started for
each. A coding CLI started somewhere else is recognised by the command names in
the agent catalog (`dodaios/workspace/agents.py`), so a new catalog entry is
recognised without a change here.

## Per platform

| | Windows | Linux | macOS |
|---|---------|-------|-------|
| Processor and memory per process | yes | yes | yes |
| Memory figure | private working set | resident size | resident size |
| Connected apps | yes | yes | only when the system allows reading other programs' connections |
| Graphics card load | any vendor, from the system's counters | NVIDIA, through `nvidia-smi` | no reading |
| Graphics memory per process | yes | compute processes on NVIDIA | no |

Where a reading does not exist the view says so. It never shows a zero in its
place.

## Limits

- A process that starts and ends between two readings is not seen as a row. Its
  processor time still counts, under "everything else".
- Memory is summed per process. Pages shared between processes are counted for
  each of them, so a group can read slightly high.
- An agent on another computer is not measured here.
