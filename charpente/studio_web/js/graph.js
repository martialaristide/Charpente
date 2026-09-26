// The target graph as SVG: layered layout (dependencies on the left), with the critical path highlighted.
// `layout` is pure (nodes/edges in, positions out); `render` builds the SVG.

/** Assign each node a layer = longest chain of dependencies below it, then order nodes inside a layer to reduce crossings (barycenter). */
export function layout(nodes, edges, { xGap = 190, yGap = 54, nodeWidth = 150, nodeHeight = 32 } = {}) {
  const names = nodes.map((n) => n.name);
  const dependencies = new Map(names.map((n) => [n, []]));
  for (const { from, to } of edges) if (dependencies.has(from) && dependencies.has(to)) dependencies.get(from).push(to); // from needs to
  const layer = new Map();
  const visiting = new Set();
  const depth = (name) => {
    if (layer.has(name)) return layer.get(name);
    if (visiting.has(name)) return 0; // a cycle cannot exist in a loaded workspace; never loop on bad input
    visiting.add(name);
    const value = dependencies.get(name).reduce((max, dep) => Math.max(max, depth(dep) + 1), 0);
    visiting.delete(name);
    layer.set(name, value);
    return value;
  };
  names.forEach(depth);
  const columns = [];
  for (const name of names) (columns[layer.get(name)] ||= []).push(name);
  const order = new Map();
  columns.forEach((column, index) => {
    if (index > 0) {
      const center = (name) => {
        const linked = edges.filter((e) => e.to === name || e.from === name).map((e) => (e.to === name ? e.from : e.to));
        const known = linked.filter((l) => order.has(l));
        return known.length ? known.reduce((sum, l) => sum + order.get(l), 0) / known.length : 0;
      };
      column.sort((a, b) => center(a) - center(b) || a.localeCompare(b));
    } else {
      column.sort();
    }
    column.forEach((name, row) => order.set(name, row));
  });
  const positions = {};
  columns.forEach((column, index) => {
    column.forEach((name, row) => {
      positions[name] = { x: 12 + index * xGap, y: 12 + row * yGap, width: nodeWidth, height: nodeHeight, layer: index };
    });
  });
  const width = 24 + Math.max(0, columns.length - 1) * xGap + nodeWidth;
  const height = 24 + Math.max(0, ...columns.map((c) => c.length - 1)) * yGap + nodeHeight;
  return { positions, width, height };
}

const NS = "http://www.w3.org/2000/svg";
function svg(tag, attrs = {}, text) {
  const element = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) element.setAttribute(k, String(v));
  if (text !== undefined) element.textContent = text;
  return element;
}

/** Draw the graph. `critical` is the list of target names on the critical path (in order); `costs` maps target → seconds. */
export function render(container, graph, { critical = [], costs = {}, onSelect = () => {} } = {}) {
  container.textContent = "";
  const { positions, width, height } = layout(graph.nodes, graph.edges);
  const onPath = new Set(critical);
  const criticalEdges = new Set(critical.slice(1).map((name, i) => `${name}>${critical[i]}`)); // later target needs the earlier one
  const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, width, height, role: "img", "aria-label": "target dependency graph" });
  const defs = svg("defs");
  const marker = svg("marker", { id: "arrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
  marker.append(svg("path", { d: "M 0 0 L 10 5 L 0 10 z", class: "graph-arrow" }));
  defs.append(marker);
  root.append(defs);
  for (const { from, to } of graph.edges) {
    const a = positions[from];
    const b = positions[to];
    if (!a || !b) continue;
    const x1 = b.x + b.width;
    const y1 = b.y + b.height / 2;
    const x2 = a.x;
    const y2 = a.y + a.height / 2;
    const mid = (x1 + x2) / 2;
    root.append(svg("path", { d: `M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`, class: `graph-edge${criticalEdges.has(`${from}>${to}`) ? " critical" : ""}`,
      "marker-end": "url(#arrow)", fill: "none" }));
  }
  for (const node of graph.nodes) {
    const p = positions[node.name];
    const group = svg("g", { class: `graph-node kind-${node.kind}${node.external ? " external" : ""}${onPath.has(node.name) ? " critical" : ""}`, tabindex: 0,
      role: "button", "aria-label": `${node.name}, ${node.kind}` });
    group.append(svg("rect", { x: p.x, y: p.y, width: p.width, height: p.height, rx: 6 }));
    group.append(svg("text", { x: p.x + 10, y: p.y + 14, class: "graph-name" }, node.name.length > 20 ? node.name.slice(0, 19) + "…" : node.name));
    const detail = costs[node.name] !== undefined ? `${node.kind} · ${costs[node.name].toFixed(2)} s` : node.kind;
    group.append(svg("text", { x: p.x + 10, y: p.y + 26, class: "graph-detail" }, detail));
    group.append(svg("title", {}, `${node.name} (${node.kind}${node.external ? ", package" : ""})`));
    group.addEventListener("click", () => onSelect(node.name));
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onSelect(node.name);
      }
    });
    root.append(group);
  }
  container.append(root);
  return root;
}
