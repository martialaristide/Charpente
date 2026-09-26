// Profile panel: where the last build spent its time (per target, per action) and which headers are the most expensive to touch.
// The history database stores each action's duration, not its start time, so this is a ranking, not a timeline.
import { clear, formatSeconds, h } from "../util.js";

export function bars(items, key = "value") {
  /** [{label, value}] → the same with `percent` relative to the largest value (0 when all are 0). */
  const max = Math.max(0, ...items.map((i) => i[key]));
  return items.map((item) => ({ ...item, percent: max > 0 ? Math.round((item[key] / max) * 100) : 0 }));
}

export function mountProfile(ctx, element) {
  const { rpc, t } = ctx;
  const body = h("div", { class: "profile-body" });
  clear(element).append(h("div", { class: "toolbar" }, h("button", { class: "small", onclick: paint }, "⟳ ", t("refresh"))), body);

  function bar(label, value, percent, extra = "") {
    return h("li", { class: "bar-row" }, h("span", { class: "bar-label", title: label }, label),
      h("span", { class: "bar-track" }, h("span", { class: "bar-fill", style: `width:${percent}%` })), h("span", { class: "bar-value" }, value), extra);
  }

  async function paint() {
    clear(body);
    try {
      const [profile, headers] = await Promise.all([rpc.request("charpente/profile"), rpc.request("charpente/headers")]);
      if (!profile.session) {
        body.append(h("p", { class: "muted" }, t("profile.none")));
        return;
      }
      const s = profile.session;
      body.append(h("p", {}, t("profile.session", { command: s.command, config: s.config, seconds: formatSeconds(s.duration), executed: s.executed, cached: s.cached })));
      const targets = bars(Object.entries(profile.targets).map(([label, c]) => ({ label, value: c.total })).sort((a, b) => b.value - a.value));
      body.append(h("h4", {}, t("profile.targets")), h("ul", { class: "bars" }, targets.map((x) => bar(x.label, formatSeconds(x.value), x.percent,
        profile.criticalPath.includes(x.label) ? h("span", { class: "badge", title: t("profile.critical") }, "●") : null))));
      const actions = bars(profile.actions.slice(0, 15).map((a) => ({ label: `${a.target} · ${a.action.split(/[\\/]/).pop()}`, value: a.duration || 0, status: a.status })));
      body.append(h("h4", {}, t("profile.actions")), h("ul", { class: "bars" }, actions.map((x) => bar(x.label, formatSeconds(x.value), x.percent, h("span", { class: "muted" }, x.status || "")))));
      const cost = bars(headers.headers.slice(0, 10).map((x) => ({ label: x.path, value: x.cost, includedBy: x.includedBy })));
      body.append(h("h4", {}, t("profile.headers")),
        cost.length ? h("ul", { class: "bars" }, cost.map((x) => bar(x.label, formatSeconds(x.value), x.percent, h("span", { class: "muted" }, t("profile.includedBy", { count: x.includedBy }))))) : h("p", { class: "muted" }, t("profile.noHeaders")));
    } catch (error) {
      body.append(h("p", { class: "muted" }, error.message));
    }
  }

  ctx.bus.on("panel-shown:profile", paint);
  ctx.bus.on("build-end", () => { if (element.offsetParent !== null) paint(); });
}
