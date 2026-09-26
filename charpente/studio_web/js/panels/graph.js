// Graph panel: the dependency graph of the targets with the critical path of the last build highlighted.
import { render } from "../graph.js";
import { clear, formatSeconds, h } from "../util.js";

export function mountGraph(ctx, element) {
  const { rpc, t } = ctx;
  const canvas = h("div", { class: "graph-canvas" });
  const info = h("p", { class: "muted", role: "status" });
  clear(element).append(h("div", { class: "toolbar" }, h("button", { class: "small", onclick: paint }, "⟳ ", t("refresh"))), info, canvas);

  async function paint() {
    try {
      const [graph, profile] = await Promise.all([rpc.request("charpente/graph"), rpc.request("charpente/profile")]);
      const costs = Object.fromEntries(Object.entries(profile.targets).map(([name, c]) => [name, c.total]));
      render(canvas, graph, { critical: profile.criticalPath, costs, onSelect: (name) => ctx.bus.emit("select-target", name) });
      info.textContent = profile.session
        ? t("graph.critical", { chain: profile.criticalPath.join(" → ") || "–", seconds: formatSeconds(profile.criticalSeconds) })
        : t("graph.noBuild");
    } catch (error) {
      clear(canvas);
      info.textContent = error.message;
    }
  }

  ctx.bus.on("panel-shown:graph", paint);
  ctx.bus.on("build-end", () => { if (element.offsetParent !== null) paint(); });
}
