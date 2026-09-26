// Problems: every diagnostic (from builds and from the language server), grouped by file; click to jump.
import { clear, h } from "../util.js";

export function collect(diagnostics) {
  /** diagnostics: Map(source → Map(path → [diag])) → [{path, items: [{line, character, severity, message, source}]}] sorted by path. */
  const byPath = new Map();
  for (const [source, files] of diagnostics) {
    for (const [path, items] of files) {
      if (!items.length) continue;
      if (!byPath.has(path)) byPath.set(path, []);
      byPath.get(path).push(...items.map((d) => ({ ...d, source: d.source || source })));
    }
  }
  return [...byPath.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([path, items]) => ({
    path, items: items.sort((a, b) => a.line - b.line || a.character - b.character),
  }));
}

export function counts(groups) {
  let errors = 0;
  let warnings = 0;
  for (const g of groups) for (const d of g.items) (d.severity === "error" ? errors++ : d.severity === "warning" ? warnings++ : 0);
  return { errors, warnings };
}

const ICON = { error: "⛔", warning: "⚠️", information: "ℹ️", hint: "💡" };

export function mountProblems(ctx, element) {
  const { t } = ctx;
  const list = h("ul", { class: "problems" });
  clear(element).append(list);

  function paint() {
    const groups = collect(ctx.diagnostics);
    const { errors, warnings } = counts(groups);
    ctx.bus.emit("problem-counts", { errors, warnings });
    clear(list);
    if (!groups.length) list.append(h("li", { class: "muted" }, t("problems.none")));
    for (const group of groups) {
      const items = h("ul", {});
      for (const d of group.items) {
        items.append(h("li", { class: `problem ${d.severity}` },
          h("button", { class: "problem-row", onclick: () => ctx.openFile(group.path, d.line + 1, d.character + 1) },
            h("span", { class: "icon", "aria-label": t(`severity.${d.severity}`) }, ICON[d.severity] || "•"),
            h("span", { class: "message" }, d.message),
            h("span", { class: "where muted" }, `${d.source} · ${d.line + 1}:${d.character + 1}`))));
      }
      list.append(h("li", { class: "problem-file" }, h("div", { class: "file-name" }, group.path, h("span", { class: "muted" }, ` (${group.items.length})`)), items));
    }
  }

  ctx.bus.on("diagnostics-changed", paint);
  paint();
}
