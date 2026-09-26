// Explorer: the project's files as a lazy tree.
import { clear, h } from "../util.js";

export function mountFiles(ctx, element) {
  const { rpc, t } = ctx;
  const expanded = new Set([""]);
  const cache = new Map();

  const holder = h("div", { class: "tree-holder" });
  clear(element).append(
    h("div", { class: "toolbar" },
      h("button", { class: "small", title: t("files.new"), onclick: newFile }, "＋ ", t("files.new")),
      h("button", { class: "small", title: t("files.refresh"), "aria-label": t("files.refresh"), onclick: () => refresh() }, "⟳")),
    holder);

  async function list(path) {
    if (!cache.has(path)) cache.set(path, (await rpc.request("charpente/files/list", { path })).entries);
    return cache.get(path);
  }

  async function paint(path, into, depth) {
    let entries;
    try {
      entries = await list(path);
    } catch (error) {
      into.append(h("li", { class: "muted" }, error.message));
      return;
    }
    for (const entry of entries) {
      const open = entry.dir && expanded.has(entry.path);
      const row = h("li", { role: "treeitem", "aria-expanded": entry.dir ? String(open) : null });
      row.append(h("button", {
        class: `tree-row ${entry.dir ? "dir" : "file"}${ctx.activePath === entry.path ? " active" : ""}`,
        style: `padding-left:${8 + depth * 14}px`,
        "data-path": entry.path,
        onclick: async () => {
          if (!entry.dir) return ctx.openFile(entry.path);
          if (expanded.has(entry.path)) expanded.delete(entry.path);
          else expanded.add(entry.path);
          await refresh(false);
        },
      }, h("span", { class: "twisty", "aria-hidden": "true" }, entry.dir ? (open ? "▾" : "▸") : ""), h("span", { class: "name" }, entry.name)));
      if (open) {
        const children = h("ul", { role: "group" });
        row.append(children);
        await paint(entry.path, children, depth + 1);
      }
      into.append(row);
    }
  }

  async function refresh(forget = true) {
    if (forget) cache.clear();
    const root = h("ul", { class: "tree", role: "tree", "aria-label": t("tab.files") });
    await paint("", root, 0);
    clear(holder).append(root);
  }

  async function newFile() {
    const name = await ctx.ask(t("files.newPrompt"), "src/new_file.cpp");
    if (!name) return;
    try {
      await rpc.request("charpente/files/create", { path: name.trim() });
      await refresh();
      ctx.openFile(name.trim());
    } catch (error) {
      ctx.toast(error.message, "error");
    }
  }

  ctx.bus.on("files-changed", () => refresh());
  ctx.bus.on("active-file", (path) => {
    const parts = String(path || "").split("/").slice(0, -1);
    parts.forEach((_, i) => expanded.add(parts.slice(0, i + 1).join("/"))); // reveal the file: open the folders that contain it
    return refresh(false);
  });
  return { refresh };
}
