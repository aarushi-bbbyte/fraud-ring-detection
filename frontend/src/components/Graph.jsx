import { useEffect, useRef } from "react";
import cytoscape from "cytoscape";

const COLORS = {
  core: "#2a78d6", // flagged accounts (cycle members, fan hubs)
  other: "#c3c2b7", // counterparties
  focus: "#eb6834", // the account being viewed
  flaggedEdge: "#d03b3b",
  edge: "#a8a69e",
  label: "#52514e",
};

// Edge labels only stay readable on small graphs; above this they're hidden.
const MAX_LABELLED_EDGES = 80;

/**
 * Directed money-flow graph.
 * nodes: [{ id, label, kind: "core" | "other" | "focus" }]
 * edges: [{ id, source, target, label, flagged }]
 */
export default function Graph({ nodes, edges, layout = "cose", onNodeClick }) {
  const container = useRef(null);

  useEffect(() => {
    if (!container.current) return;
    const showLabels = edges.length <= MAX_LABELLED_EDGES;
    const cy = cytoscape({
      container: container.current,
      elements: [
        ...nodes.map((n) => ({ data: { id: n.id, label: n.label ?? n.id, kind: n.kind } })),
        ...edges.map((e) => ({
          data: { id: e.id, source: e.source, target: e.target, label: showLabels ? e.label : "", flagged: e.flagged ? 1 : 0 },
        })),
      ],
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)", "font-size": 9, color: COLORS.label, "text-valign": "bottom", "text-margin-y": 4,
            width: 14, height: 14, "background-color": COLORS.other, "border-width": 2, "border-color": "#fcfcfb",
          },
        },
        { selector: 'node[kind = "core"]', style: { "background-color": COLORS.core, width: 20, height: 20 } },
        { selector: 'node[kind = "focus"]', style: { "background-color": COLORS.focus, width: 24, height: 24 } },
        {
          selector: "edge",
          style: {
            width: 1.5, "line-color": COLORS.edge, "target-arrow-color": COLORS.edge, "target-arrow-shape": "triangle",
            "arrow-scale": 0.8, "curve-style": "bezier", label: "data(label)", "font-size": 8, color: COLORS.label,
            "text-background-color": "#fcfcfb", "text-background-opacity": 0.85, "text-background-padding": 1,
            "text-rotation": "autorotate",
          },
        },
        {
          selector: "edge[flagged = 1]",
          style: { width: 2, "line-color": COLORS.flaggedEdge, "target-arrow-color": COLORS.flaggedEdge },
        },
      ],
      layout: { name: layout, animate: false, padding: 30, nodeRepulsion: () => 9000, idealEdgeLength: () => 90 },
      wheelSensitivity: 0.2,
    });
    if (onNodeClick) cy.on("tap", "node", (evt) => onNodeClick(evt.target.id()));
    return () => cy.destroy();
  }, [nodes, edges, layout, onNodeClick]);

  return (
    <>
      <div ref={container} className="graph" />
      <div className="legend">
        <span><span className="dot" style={{ background: COLORS.core }} />flagged account</span>
        <span><span className="dot" style={{ background: COLORS.other }} />counterparty</span>
        {nodes.some((n) => n.kind === "focus") && (
          <span><span className="dot" style={{ background: COLORS.focus }} />this account</span>
        )}
        <span><span className="dot" style={{ background: COLORS.flaggedEdge }} />transfer in an alert</span>
        {edges.length > MAX_LABELLED_EDGES && <span className="muted">amount labels hidden ({edges.length} transfers)</span>}
      </div>
    </>
  );
}
