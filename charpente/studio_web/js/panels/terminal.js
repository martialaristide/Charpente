// Terminal: several tabs, each running commands in the project's environment (the toolchain on PATH, CC/CXX/AR set).
// Commands run as an argument list without a shell, so there are no pipes or redirections, and programs that need a
// real terminal (a pty) are not supported: see docs/studio.md. Output lines with file:line are links.
import { clear, h, parseLocation, relativeToRoot, splitCommandLine } from "../util.js";

export function mountTerminal(ctx, element) {
  const { rpc, t } = ctx;
  const tabs = h("div", { class: "subtabs", role: "tablist", "aria-label": t("tab.terminal") });
  const body = h("div", { class: "terminals" });
  clear(element).append(tabs, body);
  const sessions = [];
  let counter = 0;
  let active = null;

  function addSession() {
    counter++;
    const session = { name: `${t("terminal.name")} ${counter}`, stream: null, history: [], cursor: 0 };
    session.output = h("div", { class: "log", role: "log", tabindex: 0 });
    session.input = h("input", { class: "terminal-input", type: "text", spellcheck: "false", autocomplete: "off", "aria-label": t("terminal.command"), placeholder: t("terminal.placeholder") });
    session.stop = h("button", { class: "small", hidden: true, onclick: () => stop(session) }, "■ ", t("terminal.stop"));
    session.panel = h("div", { class: "terminal", hidden: true }, session.output, h("div", { class: "terminal-line" }, h("span", { class: "prompt" }, "›"), session.input, session.stop));
    session.tab = h("button", { role: "tab", class: "subtab", onclick: () => select(session) }, session.name,
      h("span", { class: "close", role: "button", "aria-label": t("close"), onclick: (event) => { event.stopPropagation(); close(session); } }, "✕"));
    session.input.addEventListener("keydown", (event) => onKey(session, event));
    sessions.push(session);
    tabs.insertBefore(session.tab, plus);
    body.append(session.panel);
    select(session);
    return session;
  }

  const plus = h("button", { class: "subtab plus", title: t("terminal.new"), "aria-label": t("terminal.new"), onclick: () => addSession() }, "＋");
  tabs.append(plus);

  function select(session) {
    active = session;
    for (const s of sessions) {
      s.panel.hidden = s !== session;
      s.tab.setAttribute("aria-selected", String(s === session));
      s.tab.classList.toggle("active", s === session);
    }
    session.input.focus();
  }

  async function close(session) {
    await stop(session);
    session.tab.remove();
    session.panel.remove();
    sessions.splice(sessions.indexOf(session), 1);
    if (!sessions.length) addSession();
    else if (active === session) select(sessions[sessions.length - 1]);
  }

  function say(session, text, level = "") {
    const row = h("div", { class: `line ${level}` });
    const location = parseLocation(text);
    if (location) {
      const file = relativeToRoot(location.file, ctx.info && ctx.info.root);
      row.append(text.slice(0, location.index), h("a", { href: "#", class: "loc", onclick: (event) => { event.preventDefault(); ctx.openFile(file, location.line, location.column); } },
        text.slice(location.index, location.index + location.length)), text.slice(location.index + location.length));
    } else {
      row.append(text);
    }
    session.output.append(row);
    while (session.output.childElementCount > 5000) session.output.firstChild.remove();
    session.output.scrollTop = session.output.scrollHeight;
  }

  async function run(session, text) {
    let argv;
    try {
      argv = splitCommandLine(text);
    } catch (error) {
      say(session, error.message, "error");
      return;
    }
    if (!argv.length) return;
    session.history.push(text);
    session.cursor = session.history.length;
    say(session, `› ${text}`, "command");
    if (session.stream) {
      say(session, t("terminal.busy"), "error");
      return;
    }
    try {
      session.stop.hidden = false;
      session.input.disabled = true;
      const { id } = await rpc.request("charpente/terminal/run", { argv, platform: ctx.platform() || undefined });
      session.stream = id;
      session.release = rpc.claimStream(id, (message) => onStream(session, message));
    } catch (error) {
      say(session, error.message, "error");
      session.stop.hidden = true;
      session.input.disabled = false;
    }
  }

  async function stop(session) {
    if (session.stream) await rpc.request("charpente/stream/stop", { id: session.stream }).catch(() => {});
  }

  function onKey(session, event) {
    if (event.key === "Enter") {
      const text = session.input.value;
      session.input.value = "";
      run(session, text.trim());
    } else if (event.key === "ArrowUp" && session.history.length) {
      session.cursor = Math.max(0, session.cursor - 1);
      session.input.value = session.history[session.cursor] || "";
      event.preventDefault();
    } else if (event.key === "ArrowDown" && session.history.length) {
      session.cursor = Math.min(session.history.length, session.cursor + 1);
      session.input.value = session.history[session.cursor] || "";
      event.preventDefault();
    } else if (event.key === "c" && event.ctrlKey && session.stream) {
      event.preventDefault();
      stop(session);
    } else if (event.key === "l" && event.ctrlKey) {
      event.preventDefault();
      clear(session.output);
    }
  }

  function onStream(session, message) {
    if (message.line !== undefined) {
      say(session, message.line);
    } else if (message.exit !== undefined) {
      say(session, t("terminal.exited", { code: message.exit }), message.exit === 0 ? "muted" : "error");
      if (session.release) session.release();
      session.stream = null;
      session.stop.hidden = true;
      session.input.disabled = false;
      session.input.focus();
    }
  }

  addSession();
  ctx.bus.on("panel-shown:terminal", () => active && active.input.focus());
  ctx.bus.on("terminal-run", ({ text }) => {
    const session = active || addSession();
    run(session, text);
  });
}
