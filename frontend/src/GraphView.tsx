import type { GraphShape } from "./api";
import { NODE } from "./labels";

/** The job graph as an SVG diagram. The topology comes from the compiled
 *  LangGraph graph (/api/graph); known nodes get a hand-tuned layout, any
 *  other node is placed in a row at the bottom. */

const W = 150;
const H = 42;
const LAYOUT: Record<string, [number, number]> = {
  __start__: [320, 30],
  load_posting: [320, 104],
  rule_screen: [180, 182],
  extract: [460, 182],
  decide: [320, 262],
  human_review: [140, 344],
  match_one: [440, 344],
  summarize: [440, 424],
  finalize: [320, 504],
  __end__: [320, 578],
};

export interface NodeState {
  visited: Set<string>;
  order?: string[];            // nodes in the order they ran, to tell which conditional branch was taken
  active?: string | null;      // running right now
  waiting?: string | null;     // paused here for the user
  counts?: Record<string, number>;
  seconds?: Record<string, number>;
}

function position(id: string, index: number): [number, number] {
  return LAYOUT[id] ?? [90 + (index % 4) * 160, 650 + Math.floor(index / 4) * 70];
}

/** A plain edge counts as taken when both ends ran. A conditional edge counts only
 *  when its target is the first of the source's possible targets to run after it. */
function takenEdges(graph: GraphShape, state: NodeState) {
  const taken = new Set<string>();
  const order = state.order ?? [];
  for (const edge of graph.edges) {
    if (!state.visited.has(edge.source) || !state.visited.has(edge.target)) continue;
    if (!edge.conditional || !order.length) {
      taken.add(`${edge.source}>${edge.target}`);
      continue;
    }
    const targets = new Set(graph.edges.filter((e) => e.source === edge.source).map((e) => e.target));
    const from = order.lastIndexOf(edge.source);
    const next = order.slice(from + 1).find((node) => targets.has(node));
    if (next === edge.target) taken.add(`${edge.source}>${edge.target}`);
  }
  return taken;
}

export default function GraphView({ graph, state }: { graph: GraphShape; state: NodeState }) {
  const unknown = graph.nodes.filter((n) => !LAYOUT[n.id]).map((n) => n.id);
  const taken = takenEdges(graph, state);
  const pos = (id: string) => position(id, unknown.indexOf(id));
  const height = unknown.length ? 650 + Math.ceil(unknown.length / 4) * 70 : 610;

  return (
    <svg className="graph" viewBox={`50 0 560 ${height}`} role="img" aria-label="Agent 图：节点和执行路径">
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" fill="currentColor" style={{ color: "var(--muted)" }} />
        </marker>
      </defs>
      {graph.edges.map((edge, i) => {
        const [x1, y1] = pos(edge.source);
        const [x2, y2] = pos(edge.target);
        let path: string;
        if (Math.abs(y2 - y1) < 1) {
          // Same row: a straight line between the facing sides.
          const dir = x2 > x1 ? 1 : -1;
          path = `M${x1 + (dir * W) / 2},${y1} L${x2 - (dir * W) / 2},${y2}`;
        } else if (y2 > y1) {
          const sy = y1 + H / 2;
          const ty = y2 - H / 2;
          const bend = Math.max(30, (ty - sy) / 2);
          path = `M${x1},${sy} C${x1},${sy + bend} ${x2},${ty - bend} ${x2},${ty}`;
        } else {
          // Upward (a loop back): leave and enter on the right side.
          path = `M${x1 + W / 2},${y1} C${x1 + W / 2 + 60},${y1} ${x2 + W / 2 + 60},${y2} ${x2 + W / 2},${y2}`;
        }
        const isTaken = taken.has(`${edge.source}>${edge.target}`);
        return <path key={i} d={path} markerEnd="url(#arrow)"
                     className={`edge${edge.conditional ? " conditional" : ""}${isTaken ? " taken" : ""}`} />;
      })}
      {graph.nodes.map((node) => {
        const [x, y] = pos(node.id);
        const terminal = node.id.startsWith("__");
        const cls = state.active === node.id ? "active" : state.waiting === node.id ? "waiting"
          : state.visited.has(node.id) ? "visited" : "";
        const count = state.counts?.[node.id];
        const seconds = state.seconds?.[node.id];
        const sub = [count && count > 1 ? `×${count}` : "", seconds ? `${seconds.toFixed(1)} 秒` : ""]
          .filter(Boolean).join(" · ");
        return (
          <g key={node.id} className={`node ${cls} ${terminal ? "terminal" : ""}`} transform={`translate(${x - W / 2},${y - H / 2})`}>
            <rect width={W} height={H} rx={terminal ? 21 : 9} />
            <text x={W / 2} y={sub ? 17 : 26} textAnchor="middle">{NODE[node.id] ?? node.id}</text>
            {sub && <text className="sub" x={W / 2} y={33} textAnchor="middle">{sub}</text>}
            <title>{node.id}</title>
          </g>
        );
      })}
    </svg>
  );
}
