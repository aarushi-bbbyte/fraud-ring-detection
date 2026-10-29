import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { usd, time } from "../theme.js";

// Caps keep the canvas smooth on large rings (up to ~330 accounts and 2,000 transfers).
const MAX_NODES = 250;
const MAX_LINKS = 600;

const NODE = {
  core: { fill: "#f05252", glow: "rgba(240, 82, 82, 0.95)" },
  focus: { fill: "#2dd4bf", glow: "rgba(45, 212, 191, 0.95)" },
  other: { fill: "#5b6b8a", glow: null },
};

function useWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(800);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

/**
 * Money-flow graph: particles travel along each transfer in the direction money moved,
 * node size grows with the amount an account moved, flagged accounts glow red.
 * nodes: [{ id, kind: "core" | "other" | "focus" }]
 * links: [{ id, source, target, amount, timestamp, flagged }]
 */
export default function FlowGraph({ nodes, links, onNodeClick, height = 600 }) {
  const [wrapRef, width] = useWidth();
  const fg = useRef(null);
  const fitted = useRef(false);

  const data = useMemo(() => {
    const moved = new Map();
    for (const l of links) {
      moved.set(l.source, (moved.get(l.source) ?? 0) + (l.amount ?? 0));
      moved.set(l.target, (moved.get(l.target) ?? 0) + (l.amount ?? 0));
    }
    const rank = (n) => (n.kind === "other" ? 0 : 1) * 1e18 + (moved.get(n.id) ?? 0);
    const kept = [...nodes].sort((a, b) => rank(b) - rank(a)).slice(0, MAX_NODES);
    const keep = new Set(kept.map((n) => n.id));
    const keptLinks = links
      .filter((l) => keep.has(l.source) && keep.has(l.target))
      .sort((a, b) => (b.amount ?? 0) - (a.amount ?? 0))
      .slice(0, MAX_LINKS);

    const maxMoved = Math.max(1, ...kept.map((n) => moved.get(n.id) ?? 0));
    const maxLink = Math.max(1, ...keptLinks.map((l) => l.amount ?? 0));
    // Parallel transfers between the same pair get separate curves.
    const pairKey = (l) => (l.source < l.target ? `${l.source}|${l.target}` : `${l.target}|${l.source}`);
    const pairCount = new Map();
    for (const l of keptLinks) pairCount.set(pairKey(l), (pairCount.get(pairKey(l)) ?? 0) + 1);
    const seen = new Map();
    const outLinks = keptLinks.map((l) => {
      const key = pairKey(l);
      const i = seen.get(key) ?? 0;
      seen.set(key, i + 1);
      const total = pairCount.get(key);
      return {
        ...l,
        curvature: total > 1 ? 0.18 + 0.12 * Math.floor(i / 2) : 0,
        width: 0.8 + 3 * Math.sqrt((l.amount ?? 0) / maxLink),
      };
    });
    return {
      nodes: kept.map((n) => ({ ...n, moved: moved.get(n.id) ?? 0, r: 4 + 10 * Math.sqrt((moved.get(n.id) ?? 0) / maxMoved) })),
      links: outLinks,
      hidden: nodes.length - kept.length,
    };
  }, [nodes, links]);

  useEffect(() => {
    fitted.current = false;
    // Longer links so small rings spread out instead of overlapping.
    fg.current?.d3Force("link")?.distance(70);
  }, [data]);

  const showLabels = data.nodes.length <= 15;

  return (
    <>
      <div className="graph-wrap" ref={wrapRef} style={{ height }}>
        <ForceGraph2D
          ref={fg}
          width={width}
          height={height}
          graphData={data}
          backgroundColor="rgba(0,0,0,0)"
          cooldownTicks={150}
          onEngineStop={() => {
            if (!fitted.current && fg.current) {
              fg.current.zoomToFit(500, 60);
              fitted.current = true;
              // A ring of a few accounts would otherwise be blown up to fill the canvas.
              setTimeout(() => fg.current && fg.current.zoom() > 2.2 && fg.current.zoom(2.2, 300), 550);
            }
          }}
          nodeLabel={(n) => `<div class="graph-tip"><b>${n.id}</b><br/>moved ${usd(n.moved)}</div>`}
          linkLabel={(l) => `<div class="graph-tip"><b>${usd(l.amount)}</b><br/>${time(l.timestamp)}</div>`}
          nodeCanvasObject={(n, ctx, scale) => {
            const style = NODE[n.kind] ?? NODE.other;
            ctx.save();
            if (style.glow) {
              ctx.shadowColor = style.glow;
              ctx.shadowBlur = 18;
            }
            ctx.beginPath();
            ctx.arc(n.x, n.y, n.r, 0, 2 * Math.PI);
            ctx.fillStyle = style.fill;
            ctx.fill();
            ctx.restore();
            if (showLabels || scale > 2.2) {
              ctx.font = `${11 / scale}px Inter, sans-serif`;
              ctx.fillStyle = "#a9b6cc";
              ctx.textAlign = "center";
              ctx.fillText(n.id, n.x, n.y + n.r + 11 / scale);
            }
          }}
          nodePointerAreaPaint={(n, color, ctx) => {
            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.arc(n.x, n.y, n.r + 3, 0, 2 * Math.PI);
            ctx.fill();
          }}
          linkColor={(l) => (l.flagged ? "rgba(240, 82, 82, 0.55)" : "rgba(124, 138, 165, 0.35)")}
          linkWidth={(l) => l.width}
          linkCurvature="curvature"
          linkDirectionalArrowLength={5}
          linkDirectionalArrowRelPos={0.92}
          linkDirectionalArrowColor={(l) => (l.flagged ? "#f05252" : "#7c8aa5")}
          linkDirectionalParticles={(l) => (l.flagged ? 3 : 1)}
          linkDirectionalParticleWidth={(l) => (l.flagged ? 3.5 : 2)}
          linkDirectionalParticleSpeed={0.006}
          linkDirectionalParticleColor={(l) => (l.flagged ? "#ffd2c2" : "#9fb3d1")}
          onNodeClick={(n) => onNodeClick?.(n.id)}
        />
        <div className="hint">Scroll to zoom · drag to pan · hover a transfer for its amount</div>
      </div>
      <div className="legend">
        <span><span className="dot" style={{ background: NODE.core.fill, boxShadow: `0 0 8px ${NODE.core.glow}` }} />flagged account</span>
        {nodes.some((n) => n.kind === "focus") && (
          <span><span className="dot" style={{ background: NODE.focus.fill }} />this account</span>
        )}
        <span><span className="dot" style={{ background: NODE.other.fill }} />counterparty</span>
        <span>node size = money moved · particles show direction of flow</span>
        {data.hidden > 0 && <span className="muted">{data.hidden} smaller accounts hidden</span>}
      </div>
    </>
  );
}
