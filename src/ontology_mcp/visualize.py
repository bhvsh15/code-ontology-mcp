"""
Interactive D3.js graph visualisation for the ontology graph.

Reads nodes and edges from a repo's local SQLite database and generates
a self-contained HTML file with a force-directed D3 v7 graph.  The file
is written to a system temp directory and opened in the default browser.

Features
--------
- Force-directed layout with zoom / pan
- Colour-coded nodes by type (Repository, Folder, File, Class, …)
- Directional arrows per edge type (CONTAINS, CALLS, EXTENDS, …)
- Hover tooltip showing node kind, qualified name, file path, and line
- Click legend items to toggle a node type on / off
- Search bar at the bottom to highlight / fade nodes by name

Usage
-----
    # From the command line:
    PYTHONPATH=src python -m ontology_mcp.visualize /path/to/repo

    # From Python:
    from ontology_mcp.visualize import open_graph
    open_graph("/path/to/repo")
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from ontology_mcp.sqlite_store import db_path

NODE_COLORS = {
    "Repository": "#f59e0b",
    "Folder":     "#8b5cf6",
    "File":       "#3b82f6",
    "Class":      "#10b981",
    "Function":   "#ef4444",
    "Method":     "#f97316",
    "Import":     "#6b7280",
}

EDGE_COLORS = {
    "CONTAINS": "#94a3b8",
    "DEFINES":  "#64748b",
    "IMPORTS":  "#a78bfa",
    "CALLS":    "#fb923c",
    "EXTENDS":  "#34d399",
}

_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Ontology Graph — {title}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #0f172a; font-family: system-ui, sans-serif; overflow: hidden; }}
#canvas {{ width: 100vw; height: 100vh; }}
.tooltip {{
  position: absolute; background: #1e293b; color: #e2e8f0;
  padding: 8px 12px; border-radius: 6px; font-size: 12px;
  pointer-events: none; opacity: 0; transition: opacity .15s;
  border: 1px solid #334155; max-width: 280px; word-break: break-all;
}}
#legend {{
  position: absolute; top: 16px; left: 16px; background: #1e293b;
  border: 1px solid #334155; border-radius: 8px; padding: 12px 16px;
  color: #e2e8f0; font-size: 12px;
}}
#legend h3 {{ margin-bottom: 8px; font-size: 13px; color: #94a3b8; }}
.legend-item {{ display: flex; align-items: center; gap: 8px; margin: 4px 0; cursor: pointer; }}
.legend-dot {{ width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }}
#stats {{
  position: absolute; top: 16px; right: 16px; background: #1e293b;
  border: 1px solid #334155; border-radius: 8px; padding: 12px 16px;
  color: #e2e8f0; font-size: 12px;
}}
#stats p {{ margin: 2px 0; }}
#search {{
  position: absolute; bottom: 16px; left: 50%; transform: translateX(-50%);
  background: #1e293b; border: 1px solid #334155; border-radius: 8px;
  padding: 8px 12px; color: #e2e8f0; font-size: 13px; width: 260px; outline: none;
}}
#search::placeholder {{ color: #64748b; }}
</style>
</head>
<body>
<svg id="canvas"></svg>
<div class="tooltip" id="tooltip"></div>
<div id="legend">
  <h3>Node types</h3>
  {legend_html}
</div>
<div id="stats">
  <p><b>{node_count}</b> nodes</p>
  <p><b>{edge_count}</b> edges</p>
</div>
<input id="search" placeholder="Search node…" autocomplete="off">

<script src="https://d3js.org/d3.v7.min.js"></script>
<script>
const graphData = {graph_json};
const colors = {colors_json};

const width  = window.innerWidth;
const height = window.innerHeight;

const svg = d3.select("#canvas")
  .attr("width", width).attr("height", height);

const g = svg.append("g");

// Zoom
svg.call(d3.zoom().scaleExtent([0.1, 4])
  .on("zoom", e => g.attr("transform", e.transform)));

// Arrow markers
const defs = svg.append("defs");
const edgeTypes = [...new Set(graphData.links.map(d => d.type))];
edgeTypes.forEach(t => {{
  defs.append("marker")
    .attr("id", "arrow-" + t)
    .attr("viewBox", "0 -4 8 8").attr("refX", 18).attr("refY", 0)
    .attr("markerWidth", 6).attr("markerHeight", 6)
    .attr("orient", "auto")
    .append("path").attr("d", "M0,-4L8,0L0,4")
    .attr("fill", colors.edges[t] || "#64748b");
}});

const simulation = d3.forceSimulation(graphData.nodes)
  .force("link", d3.forceLink(graphData.links).id(d => d.id).distance(80))
  .force("charge", d3.forceManyBody().strength(-200))
  .force("center", d3.forceCenter(width / 2, height / 2))
  .force("collision", d3.forceCollide(18));

const link = g.append("g").selectAll("line")
  .data(graphData.links).join("line")
  .attr("stroke", d => colors.edges[d.type] || "#64748b")
  .attr("stroke-width", 1.2).attr("stroke-opacity", 0.6)
  .attr("marker-end", d => `url(#arrow-${{d.type}})`);

const node = g.append("g").selectAll("circle")
  .data(graphData.nodes).join("circle")
  .attr("r", d => d.kind === "Repository" ? 14 : d.kind === "Folder" ? 10 : 7)
  .attr("fill", d => colors.nodes[d.kind] || "#64748b")
  .attr("stroke", "#0f172a").attr("stroke-width", 1.5)
  .style("cursor", "pointer")
  .call(d3.drag()
    .on("start", (e, d) => {{ if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
    .on("drag",  (e, d) => {{ d.fx = e.x; d.fy = e.y; }})
    .on("end",   (e, d) => {{ if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }}));

const label = g.append("g").selectAll("text")
  .data(graphData.nodes.filter(d => ["Repository","Folder","File"].includes(d.kind)))
  .join("text")
  .attr("font-size", 10).attr("fill", "#94a3b8")
  .attr("dx", 9).attr("dy", 3)
  .text(d => d.label.split("/").pop());

// Tooltip
const tip = document.getElementById("tooltip");
node.on("mouseover", (e, d) => {{
  tip.style.opacity = 1;
  tip.innerHTML = `<b>${{d.kind}}</b><br>${{d.label}}` + (d.file ? `<br><span style='color:#64748b'>${{d.file}}:${{d.line}}</span>` : "");
}}).on("mousemove", e => {{
  tip.style.left = (e.clientX + 14) + "px";
  tip.style.top  = (e.clientY - 10) + "px";
}}).on("mouseout", () => tip.style.opacity = 0);

simulation.on("tick", () => {{
  link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
  node.attr("cx", d => d.x).attr("cy", d => d.y);
  label.attr("x", d => d.x).attr("y", d => d.y);
}});

// Legend toggle
document.querySelectorAll(".legend-item").forEach(el => {{
  el.addEventListener("click", () => {{
    const kind = el.dataset.kind;
    const hidden = el.dataset.hidden === "1";
    el.dataset.hidden = hidden ? "0" : "1";
    el.style.opacity = hidden ? "1" : "0.4";
    node.filter(d => d.kind === kind).attr("display", hidden ? null : "none");
  }});
}});

// Search
document.getElementById("search").addEventListener("input", function() {{
  const q = this.value.toLowerCase();
  node.attr("opacity", d => !q || d.label.toLowerCase().includes(q) ? 1 : 0.1);
}});
</script>
</body>
</html>"""


def generate_html(repo_path: str) -> str:
    conn = sqlite3.connect(db_path(repo_path))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("SELECT id, type, props FROM nodes").fetchall()
    edge_rows = conn.execute(
        "SELECT source_id, rel_type, target_id FROM edges"
    ).fetchall()
    conn.close()

    nodes = []
    node_ids = set()
    for r in rows:
        props = json.loads(r["props"])
        node_ids.add(r["id"])
        nodes.append({
            "id": r["id"],
            "kind": r["type"],
            "label": props.get("qualname") or props.get("path") or props.get("name") or r["id"][:8],
            "file": props.get("file_path"),
            "line": props.get("lineno"),
        })

    links = [
        {"source": r["source_id"], "target": r["target_id"], "type": r["rel_type"]}
        for r in edge_rows
        if r["source_id"] in node_ids and r["target_id"] in node_ids
    ]

    title = Path(repo_path).name
    legend_html = "\n  ".join(
        f'<div class="legend-item" data-kind="{k}">'
        f'<div class="legend-dot" style="background:{c}"></div>{k}</div>'
        for k, c in NODE_COLORS.items()
    )
    colors_json = json.dumps({"nodes": NODE_COLORS, "edges": EDGE_COLORS})

    return _HTML_TEMPLATE.format(
        title=title,
        legend_html=legend_html,
        graph_json=json.dumps({"nodes": nodes, "links": links}),
        colors_json=colors_json,
        node_count=len(nodes),
        edge_count=len(links),
    )


def open_graph(repo_path: str) -> str:
    html = generate_html(repo_path)
    tmp = tempfile.NamedTemporaryFile(
        suffix=".html", delete=False, mode="w", encoding="utf-8"
    )
    tmp.write(html)
    tmp.flush()
    path = tmp.name
    tmp.close()
    subprocess.Popen(["open", path])
    return path


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    out = open_graph(repo)
    print(f"Opened: {out}")