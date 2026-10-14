import { memo, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ArrowLeftRight, ShieldAlert, UserRound, Users } from "lucide-react";
import { AgentMark } from "@/components/agentic/AgentMark";
import { plural } from "@/components/agentchat/traceEntries";
import { fill, useT } from "@/i18n";
import type { TeamMember, TeamThread } from "@/lib/teamThreadsApi";
import { cn } from "@/lib/utils";
import { clock, useMemberStatus } from "./memberLive";
import { canvasLines, exchangeLabel, latestExchange, YOU, type EdgeTier, type Exchange, type GraphEdge, type GraphNode, type TeamGraph } from "./teamGraph";

/**
 * The team room's canvas: the members and the person as nodes, every handoff
 * between them as a line labelled with what went across.
 *
 * Nothing on it is decoration. A line that a member is working on right now
 * flows; a line of the step the team is in is drawn in ink with its label; an
 * older line stays as a faint trace whose label shows on hover. The layout is
 * fixed per team size and fitted to the frame, so the picture never jumps.
 * A click on a member opens its chat beside the canvas; a click on a line
 * shows what the two exchanged.
 */

interface MemberData extends Record<string, unknown> {
  node: GraphNode;
  agent: string;
  selected: boolean;
  over: boolean;
  onOpen: (id: string) => void;
}

interface YouData extends Record<string, unknown> {
  needed: boolean;
  selected: boolean;
  onOpen: (id: string) => void;
}

interface LineData extends Record<string, unknown> {
  line: GraphEdge;
  /** Both directions as one two-way line. */
  both: boolean;
  tier: EdgeTier;
  count: number;
  from: GraphNode;
  to: GraphNode;
  label: string;
  selected: boolean;
  hovered: boolean;
  faded: boolean;
  onOpen: (id: string) => void;
}

const hidden = "!h-px !w-px !min-h-0 !min-w-0 !border-0 !bg-transparent !opacity-0";

const MemberNode = memo(function MemberNode({ data }: NodeProps<Node<MemberData>>) {
  const t = useT();
  const { node, agent, selected, over, onOpen } = data;
  const member = node.member as TeamMember;
  const status = useMemberStatus(member, over);
  const role = member.role ? t(`team_threads.member_role.${member.role}`) : "";
  return <div style={{ width: node.width, height: node.height }}>
    <Handle type="target" position={Position.Top} className={hidden} isConnectable={false} />
    <button type="button" onClick={() => onOpen(member.member_id)} data-testid={`team-node-${member.member_id}`}
    data-state={status.tone} aria-pressed={selected}
    aria-label={`${member.name}${role ? ` · ${role}` : ""} · ${status.text}`}
    className={cn(
      "nodrag nopan flex h-full w-full flex-col justify-center gap-1 rounded-lg border bg-card px-3 text-left transition-[border-color,box-shadow] duration-200",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      selected ? "border-accent shadow-[0_0_0_1px_hsl(var(--accent))]"
        : status.tone === "working" ? "border-accent/60"
          : status.tone === "waiting" ? "border-warning/70" : "border-border hover:border-border-strong",
      status.tone === "left" && "opacity-55",
    )}>
    <span className="flex min-w-0 items-center gap-2">
      <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-secondary">
        {agent ? <AgentMark agent={agent} label={member.name} variant="plain" size="sm" /> : <Users aria-hidden className="h-3.5 w-3.5 text-muted-foreground" />}
      </span>
      <span className={cn("min-w-0 flex-1 truncate text-sm font-medium text-foreground", status.tone === "left" && "line-through")}>{member.name}</span>
      {role && <span className="shrink-0 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground" data-testid={`team-role-${member.role}`}>{role}</span>}
    </span>
    <span className={cn("flex min-w-0 items-center gap-1.5 text-xs",
      status.tone === "working" ? "text-foreground" : status.tone === "waiting" ? "text-warning" : "text-muted-foreground")}>
      {status.tone === "waiting" ? <ShieldAlert aria-hidden className="h-3 w-3 shrink-0" />
        : <span aria-hidden className={cn("h-1.5 w-1.5 shrink-0 rounded-full",
          status.tone === "working" ? "team-pulse bg-accent" : "bg-border-strong")} />}
      <span className={cn("min-w-0 flex-1 truncate", status.call && "font-mono text-[11px]")}>{status.text}</span>
      {status.tone === "working" && status.seconds > 0 && <span className="shrink-0 tabular-nums text-muted-foreground">{clock(status.seconds)}</span>}
    </span>
    {member.model && !member.name.includes(member.model) && <span className="truncate pl-8 font-mono text-[10px] text-muted-foreground">{member.model}</span>}
    </button>
    <Handle type="source" position={Position.Bottom} className={hidden} isConnectable={false} />
  </div>;
});

const YouNode = memo(function YouNode({ data }: NodeProps<Node<YouData>>) {
  const t = useT();
  return <div className="h-12 w-44">
    <Handle type="target" position={Position.Top} className={hidden} isConnectable={false} />
    <button type="button" onClick={() => data.onOpen(YOU)} data-testid="team-node-you" aria-pressed={data.selected}
    className={cn(
      "nodrag nopan flex h-full w-full items-center justify-center gap-2 rounded-full border bg-card px-3 text-sm",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      data.needed ? "border-warning/70 text-foreground" : "border-border text-foreground hover:border-border-strong",
      data.selected && "border-accent",
    )}>
    <UserRound aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
    <span className="font-medium">{t("team_threads.room.you")}</span>
    {data.needed && <span className="flex items-center gap-1 text-xs text-warning"><span aria-hidden className="h-1.5 w-1.5 rounded-full bg-warning" />{t("team_threads.room.needs_you")}</span>}
    </button>
    <Handle type="source" position={Position.Bottom} className={hidden} isConnectable={false} />
  </div>;
});

/** Where the line from a node's centre towards `toward` leaves its box. */
function exit(node: GraphNode, toward: { x: number; y: number }, gap: number) {
  const dx = toward.x - node.x;
  const dy = toward.y - node.y;
  if (!dx && !dy) return { x: node.x, y: node.y };
  const scale = Math.min(dx ? (node.width / 2 + gap) / Math.abs(dx) : Infinity, dy ? (node.height / 2 + gap) / Math.abs(dy) : Infinity);
  return { x: node.x + dx * scale, y: node.y + dy * scale };
}

/** The bend of a line: both directions between two nodes bow to opposite sides. */
const BOW = 34;

/**
 * A line's path and where its label sits. The person's lines carry their label
 * near the member they reach, clear of the lines between the members.
 */
export function linePath(from: GraphNode, to: GraphNode, both = false) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy) || 1;
  const bow = both ? 0 : BOW;
  const control = { x: (from.x + to.x) / 2 - (dy / length) * bow, y: (from.y + to.y) / 2 + (dx / length) * bow };
  const start = exit(from, control, both ? 9 : 4);
  const end = exit(to, control, 9);
  // Two two-way lines crossing in the middle keep their labels apart.
  const at = from.kind === "you" ? 0.74 : both ? 0.4 : 0.5;
  const point = (a: number, b: number, c: number) => (1 - at) * (1 - at) * a + 2 * (1 - at) * at * b + at * at * c;
  const label = { x: point(start.x, control.x, end.x), y: point(start.y, control.y, end.y) };
  return { path: `M ${start.x} ${start.y} Q ${control.x} ${control.y} ${end.x} ${end.y}`, label };
}

const STROKE: Record<EdgeTier | "selected", string> = {
  selected: "stroke-[hsl(var(--accent))] [stroke-width:2]",
  live: "team-flow stroke-[hsl(var(--accent))] [stroke-width:1.75]",
  current: "stroke-[hsl(var(--foreground)/0.5)] [stroke-width:1.5]",
  past: "stroke-[hsl(var(--border-strong))] [stroke-width:1]",
};

const LineEdge = memo(function LineEdge({ id, data }: EdgeProps<Edge<LineData>>) {
  const t = useT();
  const lang = t("trace_report.locale");
  if (!data) return null;
  const { line, both, count, from, to, label, selected, hovered, faded, onOpen } = data;
  const { path, label: at } = linePath(from, to, both);
  const tier = selected ? "selected" : data.tier;
  const exchange = latestExchange(line);
  const showLabel = selected || hovered || data.tier !== "past";
  return <>
    <BaseEdge id={id} path={path} interactionWidth={18}
      className={cn("fill-none", STROKE[tier], faded && "opacity-40")}
      markerStart={both ? `url(#team-arrow-${tier})` : undefined}
      markerEnd={`url(#team-arrow-${tier})`} />
    {showLabel && label && <EdgeLabelRenderer>
      <button type="button" onClick={() => onOpen(line.id)} data-testid={`team-edge-${line.id}`} data-tier={data.tier}
        aria-label={fill(t("team_threads.room.exchange_open"), { label })}
        style={{ transform: `translate(-50%, -50%) translate(${at.x}px, ${at.y}px)` }}
        className={cn(
          "nodrag nopan pointer-events-auto absolute flex max-w-[200px] items-center gap-1.5 rounded-md border bg-card px-1.5 py-0.5 text-[11px] leading-4 shadow-sm",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          selected ? "border-accent text-foreground" : data.tier === "live" ? "border-accent/50 text-foreground"
            : data.tier === "current" ? "border-border-strong text-foreground" : "border-border text-muted-foreground",
          faded && "opacity-60",
        )}>
        {exchange && exchange.tone !== "neutral" && <span aria-hidden className={cn("h-1.5 w-1.5 shrink-0 rounded-full",
          exchange.tone === "positive" ? "bg-success" : "bg-warning")} />}
        {both && <ArrowLeftRight aria-hidden className="h-3 w-3 shrink-0 text-muted-foreground" />}
        <span className="truncate">{label}</span>
        {count > 1 && <span className="shrink-0 tabular-nums text-muted-foreground"
          title={fill(t(`team_threads.room.exchange_count_${plural(lang, count)}`), { count })}>×{count}</span>}
      </button>
    </EdgeLabelRenderer>}
  </>;
});

const nodeTypes = { member: MemberNode, you: YouNode };
const edgeTypes = { line: LineEdge };

/** Arrowheads per line state; their ink follows the theme. */
function Arrows() {
  const head = (id: string, ink: string) => <marker key={id} id={`team-arrow-${id}`} viewBox="0 0 10 10" refX="8" refY="5"
    markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M 0 1 L 9 5 L 0 9 z" className={ink} />
  </marker>;
  return <svg aria-hidden width="0" height="0" className="absolute">
    <defs>
      {head("selected", "fill-[hsl(var(--accent))]")}
      {head("live", "fill-[hsl(var(--accent))]")}
      {head("current", "fill-[hsl(var(--foreground)/0.5)]")}
      {head("past", "fill-[hsl(var(--border-strong))]")}
    </defs>
  </svg>;
}

export interface TeamCanvasProps {
  thread: TeamThread;
  graph: TeamGraph;
  agentOf: (member: TeamMember) => string;
  selectedNode: string | null;
  selectedEdge: string | null;
  onOpenNode: (id: string) => void;
  onOpenEdge: (id: string) => void;
}

function Canvas({ thread, graph, agentOf, selectedNode, selectedEdge, onOpenNode, onOpenEdge }: TeamCanvasProps) {
  const t = useT();
  const lang = t("trace_report.locale");
  const flow = useReactFlow();
  const frame = useRef<HTMLDivElement | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const over = thread.state === "done" || thread.state === "stopped" || thread.state === "failed";
  const byId = useMemo(() => new Map(graph.nodes.map((node) => [node.id, node])), [graph.nodes]);

  const nodes = useMemo<Node[]>(() => graph.nodes.map((node) => node.kind === "you"
    ? {
      id: node.id, type: "you", position: { x: node.x - node.width / 2, y: node.y - node.height / 2 },
      width: node.width, height: node.height, draggable: false, selectable: false,
      data: { needed: thread.state === "needs_input", selected: selectedNode === YOU, onOpen: onOpenNode } satisfies YouData,
    }
    : {
      id: node.id, type: "member", position: { x: node.x - node.width / 2, y: node.y - node.height / 2 },
      width: node.width, height: node.height, draggable: false, selectable: false,
      data: {
        node, agent: agentOf(node.member as TeamMember), selected: selectedNode === node.id, over, onOpen: onOpenNode,
      } satisfies MemberData,
    }), [graph.nodes, thread.state, selectedNode, onOpenNode, agentOf, over]);

  const edges = useMemo<Edge[]>(() => canvasLines(graph).flatMap(({ line, partner, tier, count }) => {
    const from = byId.get(line.from);
    const to = byId.get(line.to);
    if (!from || !to) return [];
    const exchange = latestExchange(line) as Exchange;
    const faded = [from, to].some((node) => node.member?.state === "left");
    const selected = selectedEdge === line.id || (partner !== null && selectedEdge === partner.id);
    return [{
      id: line.id, source: line.from, target: line.to, type: "line", selectable: false, focusable: false,
      // Live lines draw last, on top of the others.
      zIndex: selected ? 3 : tier === "live" ? 2 : tier === "current" ? 1 : 0,
      data: {
        line, both: partner !== null, tier, count, from, to, label: exchangeLabel(exchange, t, lang), selected,
        hovered: hovered === line.id, faded, onOpen: onOpenEdge,
      } satisfies LineData,
    }];
  }), [graph, byId, selectedEdge, hovered, onOpenEdge, t, lang]);

  // The whole team stays in the frame when the frame or the team changes size.
  const count = graph.nodes.length;
  useEffect(() => {
    const box = frame.current;
    const fit = () => void flow.fitView({ padding: 0.12, maxZoom: 1.3, duration: 0 });
    fit();
    if (!box || typeof ResizeObserver === "undefined") return;
    let pending = 0;
    const observer = new ResizeObserver(() => {
      window.cancelAnimationFrame(pending);
      pending = window.requestAnimationFrame(fit);
    });
    observer.observe(box);
    return () => { observer.disconnect(); window.cancelAnimationFrame(pending); };
  }, [flow, count]);

  return <div ref={frame} className="team-canvas relative h-full w-full" data-testid="team-canvas"
    role="group" aria-label={t("team_threads.room.canvas")}>
    <Arrows />
    <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
      fitView fitViewOptions={{ padding: 0.12, maxZoom: 1.3 }} minZoom={0.35} maxZoom={1.6}
      nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} nodesFocusable={false} edgesFocusable={false}
      zoomOnScroll={false} zoomOnDoubleClick={false} panOnScroll={false} preventScrolling={false}
      onEdgeClick={(_, edge) => onOpenEdge(edge.id)}
      onEdgeMouseEnter={(_, edge) => setHovered(edge.id)} onEdgeMouseLeave={() => setHovered(null)}
      proOptions={{ hideAttribution: true }}>
      <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
      <Controls position="bottom-right" showInteractive={false} fitViewOptions={{ padding: 0.12, maxZoom: 1.3 }} />
    </ReactFlow>
  </div>;
}

export default function TeamCanvas(props: TeamCanvasProps) {
  return <ReactFlowProvider><Canvas {...props} /></ReactFlowProvider>;
}
