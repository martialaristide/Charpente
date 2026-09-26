// Targets: what the workspace builds, with Build / Run buttons and what each target depends on.
import { clear, h } from "../util.js";

const KIND_LABEL = { executable: "▶", static_library: "▤", shared_library: "◫", plugin: "◫", header_only: "▭", test: "✓", firmware: "▦" };

export function mountTargets(ctx, element) {
  const { t } = ctx;
  const list = h("ul", { class: "target-list" });
  clear(element).append(
    h("div", { class: "toolbar" }, h("button", { class: "small primary", onclick: () => ctx.build(null) }, t("build.all"))),
    list,
  );

  function paint() {
    clear(list);
    if (!ctx.targets.length) list.append(h("li", { class: "muted" }, ctx.info && ctx.info.name ? t("targets.none") : t("workspace.notLoaded")));
    for (const target of ctx.targets) {
      const runnable = target.capabilities.canRun;
      const status = ctx.targetStatus.get(target.displayName);
      list.append(h("li", { class: `target status-${status || "idle"}`, "data-target": target.displayName },
        h("span", { class: "kind", title: target.tags.join(", ") }, KIND_LABEL[ctx.kindOf(target.displayName)] || "•"),
        h("span", { class: "name" }, target.displayName),
        h("span", { class: "state", "aria-label": status ? t(`status.${status}`) : "" }, status ? t(`status.${status}`) : ""),
        h("span", { class: "actions" },
          h("button", { class: "small", title: t("build.target"), "aria-label": `${t("build.target")} ${target.displayName}`, onclick: () => ctx.build([target.displayName]) }, "⚒"),
          runnable ? h("button", { class: "small", title: t("run.target"), "aria-label": `${t("run.target")} ${target.displayName}`, onclick: () => ctx.run(target.displayName) }, "▶") : null),
        target.dependencies.length ? h("div", { class: "deps" }, t("targets.uses"), " ", target.dependencies.map((d) => ctx.nameOf(d.uri)).join(", ")) : null));
    }
  }

  ctx.bus.on("targets-changed", paint);
  ctx.bus.on("target-status", paint);
  paint();
}
