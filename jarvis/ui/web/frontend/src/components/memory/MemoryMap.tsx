/**
 * The memory map: every page with content as a node, every link (solid) and
 * plain-text mention (dashed) as an edge.
 *
 * Ink only, no hue: knowledge pages in body ink, agent pages one step
 * quieter, the page in focus and its neighbours in the accent. Size follows
 * connectedness, names show for the hubs and for whatever the pointer is on.
 * Colours come from the theme tokens and follow a light/dark switch live.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, { type ForceGraphMethods, type LinkObject, type NodeObject } from "react-force-graph-2d";
import { useQuery } from "@tanstack/react-query";
import { Maximize, Network } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { MEMORY_KEYS, fetchMemoryMap, type MapEdge, type MapNode } from "@/lib/memoryApi";
import { EmptyState } from "@/components/ui/empty-state";

type GraphNode = NodeObject<MapNode & { radius: number }>;
type GraphLink = LinkObject<GraphNode, { kind: MapEdge["kind"] }>;

interface Palette {
  ink: string;
  quiet: string;
  faint: string;
  edge: string;
  edgeStrong: string;
  accent: string;
  background: string;
}

function readPalette(): Palette {
  const style = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) => {
    const value = style.getPropertyValue(name).trim();
    return value ? `hsl(${value})` : fallback;
  };
  const alpha = (name: string, a: number, fallback: string) => {
    const value = style.getPropertyValue(name).trim();
    return value ? `hsl(${value} / ${a})` : fallback;
  };
  return {
    ink: token("--foreground", "#fafafa"),
    quiet: token("--muted-foreground", "#a1a1a1"),
    faint: token("--foreground-faint", "#7a7a7a"),
    edge: alpha("--foreground", 0.22, "rgba(255,255,255,0.22)"),
    edgeStrong: alpha("--accent", 0.75, "#3d8bff"),
    accent: token("--accent", "#3d8bff"),
    background: token("--background", "#0a0a0a"),
  };
}

/**
 * A gentle pull of every node toward the origin. Without it a page with no
 * links feels only repulsion, drifts to the edge, and fitting the view to it
 * shrinks the connected part of the vault to a speck.
 */
function centringForce(strength: number) {
  let nodes: GraphNode[] = [];
  const force = (alpha: number) => {
    for (const node of nodes) {
      node.vx = (node.vx ?? 0) - (node.x ?? 0) * strength * alpha;
      node.vy = (node.vy ?? 0) - (node.y ?? 0) * strength * alpha;
    }
  };
  force.initialize = (next: GraphNode[]) => {
    nodes = next;
  };
  return force;
}

const fitsConnected = (node: GraphNode) => node.degree > 0;

function usePalette(): Palette {
  const [palette, setPalette] = useState<Palette>(() => readPalette());
  useEffect(() => {
    const observer = new MutationObserver(() => setPalette(readPalette()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "style", "data-theme"] });
    return () => observer.disconnect();
  }, []);
  return palette;
}

function useSize<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize((prev) => (Math.abs(prev.width - width) < 1 && Math.abs(prev.height - height) < 1 ? prev : { width, height }));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, size] as const;
}

export function MemoryMap({
  focus,
  onOpen,
  compact = false,
}: {
  focus: string | null;
  onOpen: (path: string) => void;
  /** No toolbar and no legend: for a card that embeds the map. */
  compact?: boolean;
}) {
  const t = useT();
  const [includeAgents, setIncludeAgents] = useState(true);
  const query = useQuery({
    queryKey: MEMORY_KEYS.map(includeAgents),
    queryFn: () => fetchMemoryMap(includeAgents),
    staleTime: 10_000,
  });
  const palette = usePalette();
  const [containerRef, size] = useSize<HTMLDivElement>();
  const graphRef = useRef<ForceGraphMethods<GraphNode, GraphLink>>();
  const [hover, setHover] = useState<string | null>(null);
  const framed = useRef(false);

  const data = useMemo(() => {
    const nodes: GraphNode[] = (query.data?.nodes ?? []).map((node) => ({
      ...node,
      radius: 2.6 + Math.min(Math.sqrt(node.degree), 7) * 1.25,
    }));
    const links: GraphLink[] = (query.data?.edges ?? []).map((edge) => ({ ...edge }));
    return { nodes, links };
  }, [query.data]);

  const neighbours = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const edge of query.data?.edges ?? []) {
      if (!map.has(edge.source)) map.set(edge.source, new Set());
      if (!map.has(edge.target)) map.set(edge.target, new Set());
      map.get(edge.source)?.add(edge.target);
      map.get(edge.target)?.add(edge.source);
    }
    return map;
  }, [query.data]);

  const labelled = useMemo(() => {
    const ranked = [...(query.data?.nodes ?? [])].sort((a, b) => b.degree - a.degree);
    return new Set(ranked.slice(0, 14).map((node) => node.id));
  }, [query.data]);

  const active = hover ?? focus;
  const activeSet = useMemo(() => {
    if (!active) return null;
    return new Set([active, ...(neighbours.get(active) ?? [])]);
  }, [active, neighbours]);

  // Spread the layout (library defaults pack a few hundred pages into a
  // ball), then frame it while it settles. The graph only exists once the
  // container has a size, so this waits for that too.
  const mounted = size.width > 0 && size.height > 0;
  useEffect(() => {
    const graph = graphRef.current;
    if (!graph || !mounted) return;
    const charge = graph.d3Force("charge") as unknown as
      | { strength?: (v: number) => void; distanceMax?: (v: number) => void }
      | undefined;
    charge?.strength?.(-70);
    charge?.distanceMax?.(420);
    const link = graph.d3Force("link") as unknown as { distance?: (v: number) => void } | undefined;
    link?.distance?.(46);
    graph.d3Force("centre", centringForce(0.08) as never);
    framed.current = false;
    graph.d3ReheatSimulation();
    if (focus) return;
    // Framing an unsettled layout once leaves the cloud growing past the
    // edges, so frame a few times while it spreads.
    const timers = [700, 1800, 3500].map((ms) =>
      window.setTimeout(() => graphRef.current?.zoomToFit(400, 48, fitsConnected), ms),
    );
    return () => timers.forEach((id) => window.clearTimeout(id));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-run per data set, not per focus change
  }, [data, mounted]);

  // Bring the focused page into view once the layout has settled.
  useEffect(() => {
    if (!focus) return;
    const id = window.setTimeout(() => {
      const node = data.nodes.find((item) => item.id === focus);
      if (node && typeof node.x === "number" && typeof node.y === "number") {
        graphRef.current?.centerAt(node.x, node.y, 600);
        graphRef.current?.zoom(2.4, 600);
      }
    }, 900);
    return () => window.clearTimeout(id);
  }, [focus, data]);

  const paintNode = useCallback(
    (node: GraphNode, ctx: CanvasRenderingContext2D, scale: number) => {
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      const isActive = node.id === active;
      const lit = activeSet?.has(node.id) ?? false;
      const dimmed = activeSet !== null && !lit;
      // Zooming in should reveal the structure, not blow discs up: radii grow
      // with the square root of the zoom only.
      const radius = (isActive ? node.radius + 1.5 : node.radius) / Math.max(1, Math.sqrt(scale));
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.globalAlpha = dimmed ? 0.18 : 1;
      if (node.group === "agents") {
        ctx.fillStyle = palette.background;
        ctx.fill();
        ctx.lineWidth = 1.2 / Math.max(scale, 0.6);
        ctx.strokeStyle = lit ? palette.accent : palette.quiet;
        ctx.stroke();
      } else {
        ctx.fillStyle = isActive || lit ? palette.accent : palette.ink;
        ctx.fill();
      }
      const showLabel = isActive || (lit && activeSet !== null) || (activeSet === null && labelled.has(node.id)) || scale > 4;
      if (showLabel) {
        const fontSize = Math.max(11 / scale, 2.4);
        ctx.font = `${isActive ? 600 : 500} ${fontSize}px Inter, ui-sans-serif, system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        const label = node.title.length > 36 ? `${node.title.slice(0, 34)}…` : node.title;
        ctx.lineWidth = 3 / scale;
        ctx.strokeStyle = palette.background;
        ctx.strokeText(label, x, y + radius + 2 / scale);
        ctx.fillStyle = isActive ? palette.ink : node.group === "agents" ? palette.faint : palette.quiet;
        ctx.fillText(label, x, y + radius + 2 / scale);
      }
      ctx.globalAlpha = 1;
    },
    [active, activeSet, labelled, palette],
  );

  const linkColor = useCallback(
    (link: GraphLink) => {
      const source = typeof link.source === "object" ? (link.source as GraphNode).id : link.source;
      const target = typeof link.target === "object" ? (link.target as GraphNode).id : link.target;
      if (active && (source === active || target === active)) return palette.edgeStrong;
      return activeSet ? "rgba(0,0,0,0)" : palette.edge;
    },
    [active, activeSet, palette],
  );

  const counts = useMemo(() => {
    const nodes = query.data?.nodes ?? [];
    return {
      knowledge: nodes.filter((node) => node.group !== "agents").length,
      agents: nodes.filter((node) => node.group === "agents").length,
      links: (query.data?.edges ?? []).filter((edge) => edge.kind === "link").length,
      mentions: (query.data?.edges ?? []).filter((edge) => edge.kind === "mention").length,
    };
  }, [query.data]);

  return (
    <div className="relative flex min-h-0 flex-1 flex-col" data-testid="memory-map">
      {!compact && (
      <div className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-4">
        <h2 className="text-base font-semibold text-foreground-strong">{t("memory_view.map")}</h2>
        <span className="hidden text-sm text-muted-foreground md:inline">
          {fill(t("memory_view.map_counts"), { pages: counts.knowledge + counts.agents, links: counts.links, mentions: counts.mentions })}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <label className="flex h-8 cursor-pointer items-center gap-2 rounded-md px-2 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground">
            <input
              type="checkbox"
              checked={includeAgents}
              onChange={(event) => setIncludeAgents(event.target.checked)}
              className="h-3.5 w-3.5 accent-[hsl(var(--accent))]"
            />
            {t("memory_view.map_include_agents")}
          </label>
          <button
            type="button"
            onClick={() => graphRef.current?.zoomToFit(500, 48, fitsConnected)}
            className="inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground"
          >
            <Maximize className="h-3.5 w-3.5" aria-hidden />
            {t("memory_view.map_fit")}
          </button>
        </div>
      </div>
      )}

      <div ref={containerRef} className="relative min-h-0 flex-1 overflow-hidden">
        {query.isError ? (
          <div className="flex h-full items-center justify-center">
            <EmptyState icon={<Network />} title={t("memory_view.map_error")} />
          </div>
        ) : !query.isLoading && data.nodes.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <EmptyState icon={<Network />} title={t("memory_view.map_empty_title")} description={t("memory_view.map_empty_body")} />
          </div>
        ) : size.width > 0 && size.height > 0 ? (
          <ForceGraph2D<GraphNode, GraphLink>
            ref={graphRef}
            width={size.width}
            height={size.height}
            graphData={data}
            backgroundColor="rgba(0,0,0,0)"
            nodeId="id"
            nodeLabel={() => ""}
            nodeRelSize={1}
            nodeVal={(node) => node.radius * node.radius}
            nodeCanvasObject={paintNode}
            nodePointerAreaPaint={(node, color, ctx) => {
              ctx.fillStyle = color;
              ctx.beginPath();
              ctx.arc(node.x ?? 0, node.y ?? 0, node.radius + 3, 0, Math.PI * 2);
              ctx.fill();
            }}
            linkColor={linkColor}
            linkWidth={(link) => (link.kind === "link" ? 1 : 0.8)}
            linkLineDash={(link) => (link.kind === "mention" ? [2, 3] : null)}
            cooldownTicks={140}
            onEngineStop={() => {
              if (framed.current) return;
              framed.current = true;
              if (!focus) graphRef.current?.zoomToFit(400, 48, fitsConnected);
            }}
            onNodeHover={(node) => setHover(node ? String(node.id) : null)}
            onNodeClick={(node) => onOpen(String(node.id))}
            onBackgroundClick={() => setHover(null)}
          />
        ) : null}

        {!compact && (
        <div className="pointer-events-none absolute bottom-4 left-4 flex flex-col gap-1.5 rounded-lg border border-border bg-popover/90 px-3 py-2.5 text-xs text-muted-foreground backdrop-blur-sm">
          <LegendRow swatch={<span className="h-2.5 w-2.5 rounded-full bg-foreground" />} label={fill(t("memory_view.map_legend_knowledge"), { count: counts.knowledge })} />
          {includeAgents && (
            <LegendRow
              swatch={<span className="h-2.5 w-2.5 rounded-full border border-muted-foreground" />}
              label={fill(t("memory_view.map_legend_agents"), { count: counts.agents })}
            />
          )}
          <LegendRow swatch={<span className="h-px w-4 bg-foreground/50" />} label={t("memory_view.map_legend_link")} />
          <LegendRow swatch={<span className={cn("w-4 border-t border-dashed border-foreground/50")} />} label={t("memory_view.map_legend_mention")} />
        </div>
        )}
      </div>
    </div>
  );
}

function LegendRow({ swatch, label }: { swatch: JSX.Element; label: string }) {
  return (
    <span className="flex items-center gap-2">
      <span className="flex w-4 justify-center">{swatch}</span>
      {label}
    </span>
  );
}

export default MemoryMap;
