// Packages: search the recipes, add one to `ws.requires`, remove, install.
import { clear, debounce, h } from "../util.js";

export function mountPackages(ctx, element) {
  const { rpc, t } = ctx;
  const search = h("input", { type: "search", placeholder: t("packages.search"), "aria-label": t("packages.search") });
  const results = h("ul", { class: "package-results" });
  const current = h("ul", { class: "package-current" });
  const output = h("pre", { class: "output small-output", hidden: true });
  const notice = h("p", { class: "notice", hidden: true });
  clear(element).append(
    notice,
    h("h4", {}, t("packages.required")), current,
    h("div", { class: "toolbar" }, h("button", { class: "small", onclick: install }, t("packages.install"))),
    output,
    h("h4", {}, t("packages.find")), search, results);

  async function paintCurrent() {
    clear(current);
    let data;
    try {
      data = await rpc.request("charpente/packages/list");
    } catch (error) {
      current.append(h("li", { class: "muted" }, error.message));
      return;
    }
    notice.hidden = !(ctx.info && ctx.info.notice);
    notice.textContent = (ctx.info && ctx.info.notice) || "";
    if (!data.requires.length) current.append(h("li", { class: "muted" }, t("packages.none")));
    for (const spec of data.requires) {
      const name = spec.split("@")[0];
      const locked = data.locked.find((p) => p.name === name);
      current.append(h("li", {}, h("span", { class: "name" }, spec), locked ? h("span", { class: "muted" }, ` ${locked.version}`) : h("span", { class: "muted" }, ` ${t("packages.notInstalled")}`),
        h("button", { class: "small", "aria-label": `${t("packages.remove")} ${spec}`, title: t("packages.remove"), onclick: () => change("remove", spec) }, "✕")));
    }
  }

  async function change(action, spec) {
    try {
      await rpc.request(`charpente/packages/${action}`, { spec });
      ctx.info = await rpc.request("charpente/reload");
      ctx.bus.emit("info-changed");
      ctx.bus.emit("files-changed");
      await ctx.refreshTargets();
      await paintCurrent();
      ctx.toast(t(action === "add" ? "packages.added" : "packages.removed", { spec }), "info");
    } catch (error) {
      ctx.toast(error.message, "error");
    }
  }

  async function install() {
    output.hidden = false;
    output.textContent = t("packages.installing");
    try {
      const result = await rpc.request("charpente/packages/install");
      output.textContent = result.output || (result.ok ? t("packages.done") : t("packages.failed"));
      if (result.ok) {
        ctx.info = await rpc.request("charpente/reload");
        ctx.bus.emit("info-changed");
        await ctx.refreshTargets();
      }
      await paintCurrent();
    } catch (error) {
      output.textContent = error.message;
    }
  }

  async function find() {
    clear(results);
    const text = search.value.trim();
    if (!text) return;
    try {
      const { packages } = await rpc.request("charpente/packages/search", { text });
      if (!packages.length) results.append(h("li", { class: "muted" }, t("packages.noMatch")));
      for (const pkg of packages) {
        results.append(h("li", {}, h("span", { class: "name" }, pkg.name), h("span", { class: "muted" }, ` ${pkg.versions.join(", ")}`),
          h("button", { class: "small", "aria-label": `${t("packages.add")} ${pkg.name}`, onclick: () => change("add", pkg.name) }, t("packages.add"))));
      }
    } catch (error) {
      results.append(h("li", { class: "muted" }, error.message));
    }
  }

  search.addEventListener("input", debounce(find, 250));
  ctx.bus.on("info-changed", paintCurrent);
  paintCurrent();
}
