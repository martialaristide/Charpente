// Assistant panel. Always opt-in and always visible: you prepare a context, see exactly what would be sent (secrets already replaced),
// and only then press Send. A proposed fix is a diff you review; Apply rebuilds, reverts if the build fails, and runs the quality gate.
import { clear, h } from "../util.js";

export function mountAi(ctx, element, helpers = {}) {
  const { rpc, t } = ctx;
  const status = h("p", { class: "ai-status", role: "status" });
  const question = h("textarea", { rows: 3, placeholder: t("ai.placeholder"), "aria-label": t("ai.question") });
  const kind = h("select", { "aria-label": t("ai.kind") },
    h("option", { value: "question" }, t("ai.kindQuestion")), h("option", { value: "error" }, t("ai.kindError")), h("option", { value: "selection" }, t("ai.kindSelection")));
  const review = h("div", { class: "ai-review", hidden: true });
  const result = h("div", { class: "ai-result", "aria-live": "polite" });
  clear(element).append(
    status,
    h("div", { class: "toolbar" }, kind, h("button", { class: "small primary", onclick: () => prepare() }, t("ai.prepare"))),
    question, review, result);

  let lastErrors = "";
  let current = null; // the prepared context

  async function refreshStatus() {
    try {
      const s = await rpc.request("charpente/ai/status");
      status.textContent = s.available ? t("ai.ready", { provider: s.provider }) : `${t("ai.notConfigured")} ${s.howTo || ""}`;
      status.className = `ai-status ${s.available ? "ok" : "off"}`;
    } catch (error) {
      status.textContent = error.message;
    }
  }

  async function prepare(overrides = {}) {
    clear(result);
    const chosen = overrides.kind || kind.value;
    const params = { kind: chosen, text: overrides.text ?? question.value };
    if (chosen === "error") params.text = overrides.text ?? (lastErrors || question.value);
    if (chosen === "selection") {
      params.path = helpers.activePath ? helpers.activePath() : "";
      params.selection = helpers.getSelection ? helpers.getSelection() : "";
      if (!params.selection) return ctx.toast(t("ai.needSelection"), "info");
    }
    try {
      current = { ...(await rpc.request("charpente/ai/context", params)), kind: chosen, mode: overrides.mode || (chosen === "error" ? "explain" : "ask") };
    } catch (error) {
      ctx.toast(error.message, "error");
      return;
    }
    showReview();
  }

  function showReview() {
    const c = current;
    review.hidden = false;
    clear(review).append(
      h("h4", {}, t("ai.willSend", { provider: c.provider })),
      h("ul", { class: "ai-items" }, c.items.map((i) => h("li", {}, `${i.label} — ${t("ai.chars", { count: i.chars })}${i.redactions ? ` — ${t("ai.redacted", { count: i.redactions })}` : ""}`)),
        c.skipped.map((s) => h("li", { class: "muted" }, `${t("ai.leftOut")} ${s}`))),
      h("details", {}, h("summary", {}, t("ai.showExact")), h("pre", { class: "ai-exact" }, c.text)),
      h("div", { class: "buttons" },
        h("button", { class: "primary", disabled: !c.available, title: c.available ? "" : t("ai.notConfigured"), onclick: send }, t("ai.send")),
        h("button", { onclick: cancel }, t("cancel")),
        c.kind === "error" ? h("button", { class: "small", onclick: () => { current.mode = "fix"; showReview(); } }, t("ai.asFix")) : null),
      c.mode === "fix" ? h("p", { class: "muted" }, t("ai.fixNote")) : null);
  }

  function cancel() {
    current = null;
    review.hidden = true;
    clear(review);
  }

  async function send() {
    const c = current;
    if (!c) return;
    review.hidden = true;
    clear(result).append(h("p", { class: "muted" }, t("ai.waiting", { provider: c.provider })));
    try {
      const answer = await rpc.request("charpente/ai/send", { id: c.id, mode: c.mode });
      clear(result);
      if (answer.mode === "fix") showProposal(answer);
      else result.append(h("h4", {}, t("ai.answer")), h("pre", { class: "ai-answer" }, answer.answer));
    } catch (error) {
      clear(result).append(h("p", { class: "notice" }, error.message));
    }
  }

  function showProposal(proposal) {
    result.append(
      h("h4", {}, t("ai.proposal")), proposal.explanation ? h("p", {}, proposal.explanation) : null,
      h("pre", { class: "ai-diff" }, proposal.diff.split("\n").map((line) => h("span", { class: line.startsWith("+") && !line.startsWith("+++") ? "add" : line.startsWith("-") && !line.startsWith("---") ? "del" : "ctx" }, line + "\n"))),
      h("div", { class: "buttons" },
        h("button", { class: "primary", onclick: () => apply(proposal) }, t("ai.apply")),
        h("button", { onclick: () => clear(result) }, t("ai.discard"))),
      h("p", { class: "muted" }, t("ai.applyNote")));
  }

  async function apply(proposal) {
    clear(result).append(h("p", { class: "muted" }, t("ai.applying")));
    try {
      const outcome = await rpc.request("charpente/ai/apply", { proposal: proposal.proposal, config: ctx.config() });
      clear(result);
      if (!outcome.kept) {
        result.append(h("p", { class: "notice" }, t("ai.reverted")), h("pre", { class: "output small-output" }, outcome.output));
        return;
      }
      ctx.bus.emit("files-changed");
      result.append(h("p", { class: "ok" }, t("ai.applied", { files: outcome.files.join(", ") })),
        h("p", { class: outcome.gate && outcome.gate.ok ? "ok" : "notice" }, outcome.gate ? (outcome.gate.ok ? t("check.passed") : t("check.failed")) : ""));
    } catch (error) {
      clear(result).append(h("p", { class: "notice" }, error.message));
    }
  }

  ctx.bus.on("build-start", () => (lastErrors = ""));
  ctx.bus.on("build-log", ({ text, level }) => { if (level === "error") lastErrors += `${text}\n`; });
  ctx.bus.on("ai-explain", ({ text }) => {
    ctx.showPanel("ai");
    kind.value = "error";
    prepare({ kind: "error", text: text || lastErrors, mode: "explain" });
  });
  ctx.bus.on("panel-shown:ai", refreshStatus);
  refreshStatus();
  return { prepare };
}
