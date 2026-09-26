// Options: the workspace's `ws.option(...)` values as controls. Changes are saved in .charpente/options.toml (which every command reads).
import { clear, h } from "../util.js";

export function mountOptions(ctx, element) {
  const { rpc, t } = ctx;

  async function apply(name, value) {
    try {
      ctx.info = await rpc.request("charpente/options/set", { values: { [name]: value } });
      ctx.toast(t("options.saved", { name }), "info");
      ctx.bus.emit("info-changed");
      await ctx.refreshTargets();
    } catch (error) {
      ctx.toast(error.message, "error");
      paint();
    }
  }

  function control(name, option) {
    const label = `${name}${option.help ? ` — ${option.help}` : ""}`;
    if (option.kind === "bool") {
      return h("label", { class: "option" }, h("input", { type: "checkbox", checked: option.value === "true", "data-option": name,
        onchange: (event) => apply(name, event.target.checked) }), " ", label);
    }
    if (option.kind === "enum" || (option.choices && option.choices.length)) {
      const select = h("select", { "data-option": name, onchange: (event) => apply(name, event.target.value) },
        option.choices.map((choice) => h("option", { value: choice, selected: choice === option.value }, choice)));
      return h("label", { class: "option" }, label, " ", select);
    }
    const input = h("input", { type: option.kind === "int" ? "number" : "text", value: option.value, "data-option": name,
      onchange: (event) => apply(name, event.target.value) });
    return h("label", { class: "option" }, label, " ", input);
  }

  function paint() {
    clear(element);
    const options = (ctx.info && ctx.info.options) || {};
    const names = Object.keys(options);
    if (!names.length) {
      element.append(h("p", { class: "muted" }, t("options.none")));
      return;
    }
    element.append(h("p", { class: "muted" }, t("options.help")));
    for (const name of names) element.append(control(name, options[name]));
  }

  ctx.bus.on("info-changed", paint);
  paint();
}
