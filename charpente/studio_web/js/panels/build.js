// Build panel: live progress and log; compiler locations are links, error codes can be explained.
import { clear, h, parseLocation, relativeToRoot } from "../util.js";

const CODE = /\bCH\d{4}\b/;

export function mountBuild(ctx, element) {
  const { t, rpc } = ctx;
  const bar = h("progress", { class: "progress", max: 1, value: 0, "aria-label": t("build.progress") });
  const summary = h("span", { class: "summary", role: "status", "aria-live": "polite" }, t("build.idle"));
  const log = h("div", { class: "log", role: "log", "aria-live": "off", tabindex: 0 });
  const explainBox = h("div", { class: "explain", hidden: true });
  const hints = h("ul", { class: "hints" });
  const aiButton = h("button", { class: "small", hidden: true, onclick: () => ctx.bus.emit("ai-explain", { text: lastErrors.join("\n") }) }, "✨ ", t("ai.explainError"));
  clear(element).append(
    h("div", { class: "toolbar" }, bar, summary,
      h("button", { class: "small", onclick: () => ctx.build(null), title: "F7" }, t("build.all")),
      aiButton,
      h("button", { class: "small", onclick: reset }, t("clear"))),
    explainBox, hints, log);

  let total = 0;
  let done = 0;
  let lastErrors = [];
  let follow = true;
  log.addEventListener("scroll", () => (follow = log.scrollTop + log.clientHeight >= log.scrollHeight - 24));

  function reset() {
    clear(log);
    clear(hints);
    explainBox.hidden = true;
    aiButton.hidden = true;
    lastErrors = [];
  }

  function line(text, level = "info") {
    const row = h("div", { class: `line ${level}` });
    const location = parseLocation(text);
    if (location) {
      const file = relativeToRoot(location.file, ctx.info && ctx.info.root);
      row.append(text.slice(0, location.index),
        h("a", { href: "#", class: "loc", onclick: (event) => { event.preventDefault(); ctx.openFile(file, location.line, location.column); } }, text.slice(location.index, location.index + location.length)),
        text.slice(location.index + location.length));
    } else {
      row.append(text);
    }
    const code = CODE.exec(text);
    if (code) row.append(" ", h("button", { class: "small link", onclick: () => explain(code[0]) }, t("explain")));
    log.append(row);
    if (follow) log.scrollTop = log.scrollHeight;
    if (level === "error") {
      lastErrors.push(text);
      aiButton.hidden = false;
    }
  }

  async function explain(code) {
    try {
      const { text } = await rpc.request("charpente/explain", { code });
      explainBox.hidden = false;
      clear(explainBox).append(h("strong", {}, code), h("pre", {}, text), h("button", { class: "small", onclick: () => (explainBox.hidden = true) }, t("close")));
    } catch (error) {
      ctx.toast(error.message, "error");
    }
  }

  ctx.bus.on("build-start", ({ message }) => {
    reset();
    total = 0;
    done = 0;
    bar.max = 1;
    bar.value = 0;
    summary.textContent = message || t("build.running");
    summary.className = "summary";
  });
  ctx.bus.on("build-log", ({ text, level }) => line(text, level));
  ctx.bus.on("build-event", ({ type, payload }) => {
    if (type === "graph.analyzed") {
      total = payload.actions || 0;
      bar.max = Math.max(total, 1);
      summary.textContent = t("build.actions", { total });
    } else if (["action.finished", "action.cache_hit", "action.up_to_date", "action.failed"].includes(type)) {
      done++;
      bar.max = Math.max(total, done, 1);
      bar.value = done;
      summary.textContent = t("build.progressOf", { done, total: Math.max(total, done) });
    } else if (type === "hint.emitted") {
      hints.append(h("li", {}, "💡 ", payload.message));
    }
  });
  ctx.bus.on("build-end", ({ ok, message }) => {
    bar.value = bar.max;
    summary.textContent = message || (ok ? t("build.succeeded") : t("build.failed"));
    summary.className = `summary ${ok ? "ok" : "fail"}`;
  });
  ctx.bus.on("build-error", ({ message }) => {
    line(message, "error");
    summary.textContent = t("build.failed");
    summary.className = "summary fail";
  });
}
