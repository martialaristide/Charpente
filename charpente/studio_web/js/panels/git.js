// Git panel: status, per-file and per-hunk staging, a commit guarded by the quality gate, recent history.
import { hunkPatch, hunkStats, parseDiff } from "../diff.js";
import { clear, h } from "../util.js";

export function mountGit(ctx, element) {
  const { rpc, t } = ctx;
  const head = h("div", { class: "git-head", role: "status" });
  const sections = h("div", { class: "git-sections" });
  const diffView = h("div", { class: "git-diff", "aria-live": "polite" });
  const message = h("textarea", { class: "commit-message", rows: 3, placeholder: t("git.messagePlaceholder"), "aria-label": t("git.message") });
  const skipGate = h("input", { type: "checkbox", id: "skip-gate" });
  const output = h("pre", { class: "output small-output", hidden: true });
  const history = h("ul", { class: "git-log" });
  clear(element).append(
    h("div", { class: "git-columns" },
      h("div", { class: "git-left" }, head, sections,
        h("div", { class: "commit-box" }, message,
          h("label", {}, skipGate, " ", t("git.skipGate")),
          h("button", { class: "primary", onclick: commit }, t("git.commit")), output),
        h("h4", {}, t("git.history")), history),
      diffView));

  let selected = null;

  async function status() {
    let data;
    try {
      data = await rpc.request("charpente/git/status");
    } catch (error) {
      clear(head).append(error.message);
      clear(sections);
      clear(diffView);
      return null;
    }
    clear(head).append(h("strong", {}, data.branch || t("git.detached")), data.upstream ? h("span", { class: "muted" }, ` ⇄ ${data.upstream} (↑${data.ahead} ↓${data.behind})`) : h("span", { class: "muted" }, ` ${t("git.noUpstream")}`),
      h("button", { class: "small", onclick: paint, "aria-label": t("refresh") }, "⟳"));
    return data;
  }

  function group(title, files, kind) {
    const list = h("ul", { class: "git-files" });
    for (const path of files) {
      list.append(h("li", { class: selected && selected.path === path && selected.kind === kind ? "selected" : "" },
        h("button", { class: "file-name", onclick: () => show(path, kind) }, path),
        kind === "untracked" ? h("button", { class: "small", title: t("git.stage"), "aria-label": `${t("git.stage")} ${path}`, onclick: () => stage([path], false) }, "＋")
          : h("button", { class: "small", title: kind === "staged" ? t("git.unstage") : t("git.stage"), "aria-label": `${kind === "staged" ? t("git.unstage") : t("git.stage")} ${path}`,
            onclick: () => stage([path], kind === "staged") }, kind === "staged" ? "−" : "＋")));
    }
    return h("section", {}, h("h4", {}, `${title} (${files.length})`), files.length ? list : h("p", { class: "muted" }, t("git.nothing")));
  }

  async function stage(paths, unstage) {
    try {
      await rpc.request("charpente/git/stage", { paths, unstage });
      await paint();
    } catch (error) {
      ctx.toast(error.message, "error");
    }
  }

  async function show(path, kind) {
    selected = { path, kind };
    clear(diffView);
    if (kind === "untracked") {
      diffView.append(h("p", { class: "muted" }, t("git.untracked")), h("button", { class: "small", onclick: () => ctx.openFile(path) }, t("git.open")));
      return;
    }
    try {
      const { diff } = await rpc.request("charpente/git/diff", { path, staged: kind === "staged" });
      const files = parseDiff(diff);
      if (!files.length) diffView.append(h("p", { class: "muted" }, t("git.noDiff")));
      for (const file of files) {
        diffView.append(h("h4", {}, file.path, " ", h("button", { class: "small", onclick: () => ctx.openFile(file.path) }, t("git.open"))));
        file.hunks.forEach((hunk) => {
          const { added, removed } = hunkStats(hunk);
          diffView.append(h("div", { class: "hunk" },
            h("div", { class: "hunk-head" }, h("code", {}, hunk.header), h("span", { class: "muted" }, ` +${added} −${removed} `),
              h("button", { class: "small", onclick: () => applyHunk(file, hunk, kind === "staged") }, kind === "staged" ? t("git.unstageHunk") : t("git.stageHunk"))),
            h("pre", { class: "hunk-lines" }, hunk.lines.map((line) => h("span", { class: line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : "ctx" }, line + "\n")))));
        });
      }
    } catch (error) {
      diffView.append(h("p", { class: "muted" }, error.message));
    }
  }

  async function applyHunk(file, hunk, unstage) {
    try {
      await rpc.request("charpente/git/apply", { patch: hunkPatch(file, hunk), unstage });
      await paint();
      if (selected) await show(selected.path, unstage ? "modified" : "staged");
    } catch (error) {
      ctx.toast(error.message, "error");
    }
  }

  async function commit() {
    const text = message.value.trim();
    if (!text) {
      ctx.toast(t("git.needMessage"), "error");
      return;
    }
    output.hidden = false;
    output.textContent = t("git.committing");
    try {
      const result = await rpc.request("charpente/git/commit", { message: text, noVerify: skipGate.checked });
      output.textContent = result.output || (result.ok ? t("git.committed") : t("git.commitFailed"));
      if (result.ok) message.value = "";
      await paint();
    } catch (error) {
      output.textContent = error.message;
    }
  }

  async function paint() {
    const data = await status();
    if (!data) return;
    clear(sections).append(group(t("git.staged"), data.staged, "staged"), group(t("git.changes"), data.modified, "modified"), group(t("git.untrackedTitle"), data.untracked, "untracked"));
    try {
      const { commits } = await rpc.request("charpente/git/log", { limit: 8 });
      clear(history).append(...commits.map((c) => h("li", {}, h("code", {}, c.short), " ", c.subject)));
    } catch {
      clear(history);
    }
  }

  ctx.bus.on("panel-shown:git", paint);
  ctx.bus.on("files-saved", () => { if (element.offsetParent !== null) paint(); });
}
