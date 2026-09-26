// Debug panel: start a target under gdb / lldb-dap (through `charpente debug-adapter`), breakpoints, stepping, call stack, variables, watch.
import { DapClient } from "../dap.js";
import { clear, h, relativeToRoot } from "../util.js";

export function mountDebug(ctx, element) {
  const { rpc, t } = ctx;
  const dap = new DapClient(rpc);
  ctx.dap = dap;
  const targetSelect = h("select", { "aria-label": t("debug.target") });
  const argsInput = h("input", { type: "text", placeholder: t("debug.args"), "aria-label": t("debug.args"), size: 22 });
  const status = h("span", { class: "debug-status", role: "status" }, t("debug.idle"));
  const buttons = {
    start: h("button", { class: "small primary", onclick: () => start() }, "▶ ", t("debug.start")),
    cont: h("button", { class: "small", onclick: () => step("continue"), title: "F5" }, t("debug.continue")),
    over: h("button", { class: "small", onclick: () => step("next"), title: "F10" }, t("debug.stepOver")),
    into: h("button", { class: "small", onclick: () => step("stepIn"), title: "F11" }, t("debug.stepInto")),
    out: h("button", { class: "small", onclick: () => step("stepOut"), title: "Shift+F11" }, t("debug.stepOut")),
    stop: h("button", { class: "small", onclick: () => dap.stop(), title: "Shift+F5" }, "■ ", t("debug.stop")),
  };
  const stack = h("ul", { class: "debug-stack", "aria-label": t("debug.stack") });
  const variables = h("div", { class: "debug-variables", "aria-label": t("debug.variables") });
  const watchInput = h("input", { type: "text", placeholder: t("debug.watch"), "aria-label": t("debug.watch") });
  const watchResult = h("pre", { class: "output small-output", hidden: true });
  const breakpointList = h("ul", { class: "debug-breakpoints" });
  const output = h("div", { class: "log", role: "log", tabindex: 0 });
  clear(element).append(
    h("div", { class: "toolbar" }, targetSelect, argsInput, buttons.start, buttons.cont, buttons.over, buttons.into, buttons.out, buttons.stop, status),
    h("div", { class: "debug-columns" },
      h("div", {}, h("h4", {}, t("debug.stack")), stack, h("h4", {}, t("debug.breakpoints")), breakpointList),
      h("div", {}, h("h4", {}, t("debug.variables")), variables, watchInput, watchResult),
      h("div", {}, h("h4", {}, t("debug.output")), output)));

  let state = "idle"; // idle | starting | running | stopped
  let thread = null;
  let frames = [];
  let selectedFrame = null;

  function setState(next, text) {
    state = next;
    status.textContent = text || t(`debug.${next}`);
    buttons.start.disabled = next !== "idle";
    for (const key of ["cont", "over", "into", "out"]) buttons[key].disabled = next !== "stopped";
    buttons.stop.disabled = next === "idle";
    document.body.classList.toggle("debugging", next !== "idle");
    ctx.bus.emit("debug-state", { state: next });
  }

  function log(text, level = "") {
    output.append(h("div", { class: `line ${level}` }, text));
    output.scrollTop = output.scrollHeight;
  }

  function fillTargets() {
    const previous = targetSelect.value;
    clear(targetSelect).append(...ctx.targets.filter((x) => x.capabilities.canRun).map((x) => h("option", { value: x.displayName, selected: x.displayName === previous }, x.displayName)));
  }

  function absolute(path) {
    return /^([A-Za-z]:)?[\\/]/.test(path) ? path : `${ctx.root.replace(/[\\/]+$/, "")}/${path}`;
  }

  async function sendBreakpoints(client, only) {
    for (const [path, lines] of ctx.breakpoints) {
      if (only && path !== only) continue;
      await client.setBreakpoints(absolute(path), [...lines].sort((a, b) => a - b));
    }
  }

  async function start() {
    if (state !== "idle") return;
    if (!targetSelect.value) return ctx.toast(t("debug.noTarget"), "info");
    if (!(await ctx.saveAll())) return;
    clear(output);
    clear(stack);
    clear(variables);
    setState("starting");
    ctx.showPanel("debug");
    try {
      const args = argsInput.value.trim() ? argsInput.value.trim().split(/\s+/) : [];
      await dap.start({ target: targetSelect.value, config: ctx.config(), args }, (client) => sendBreakpoints(client));
      if (state === "starting") setState("running");
    } catch (error) {
      log(error.message, "error");
      ctx.toast(error.message, "error");
      if (state !== "idle") cleanup();
    }
  }

  function cleanup() {
    thread = null;
    frames = [];
    selectedFrame = null;
    ctx.bus.emit("execution-line", null);
    setState("idle");
  }

  async function step(kind) {
    if (state !== "stopped" || thread === null) return;
    setState("running");
    ctx.bus.emit("execution-line", null);
    try {
      await dap[kind](thread);
    } catch (error) {
      log(error.message, "error");
    }
  }

  async function showStopped(body) {
    thread = body.threadId ?? thread;
    if (thread === null || thread === undefined) {
      try {
        thread = ((await dap.threads()).threads[0] || {}).id ?? 1;
      } catch {
        thread = 1;
      }
    }
    setState("stopped", t("debug.stoppedBecause", { reason: body.reason || "" }));
    try {
      frames = (await dap.stackTrace(thread)).stackFrames || [];
    } catch (error) {
      log(error.message, "error");
      return;
    }
    clear(stack).append(...frames.map((frame, index) => h("li", {}, h("button", { class: `frame${index === 0 ? " top" : ""}`, onclick: () => selectFrame(frame) },
      h("strong", {}, frame.name), " ", h("span", { class: "muted" }, frame.source ? `${frame.source.name || frame.source.path}:${frame.line}` : "")))));
    if (frames.length) await selectFrame(frames[0]);
  }

  async function selectFrame(frame) {
    selectedFrame = frame;
    if (frame.source && frame.source.path) {
      const path = relativeToRoot(frame.source.path, ctx.root);
      await ctx.openFile(path, frame.line, 1);
      ctx.bus.emit("execution-line", { path, line: frame.line });
    }
    await showVariables(frame);
  }

  async function showVariables(frame) {
    clear(variables);
    try {
      for (const scope of (await dap.scopes(frame.id)).scopes) {
        variables.append(h("div", { class: "scope" }, h("strong", {}, scope.name)));
        const list = h("ul", { class: "vars" });
        variables.append(list);
        await fillVariables(list, scope.variablesReference, 0);
      }
    } catch (error) {
      variables.append(h("p", { class: "muted" }, error.message));
    }
  }

  async function fillVariables(list, reference, depth) {
    const { variables: items } = await dap.variables(reference);
    for (const item of items) {
      const row = h("li", { style: `padding-left:${depth * 14}px` },
        item.variablesReference ? h("button", { class: "twisty-button", "aria-label": t("debug.expand"), onclick: async (event) => {
          const button = event.currentTarget;
          if (button.dataset.open) { button.dataset.open = ""; button.textContent = "▸"; while (row.nextSibling && row.nextSibling.dataset && row.nextSibling.dataset.parent === String(reference) + item.name) row.nextSibling.remove(); return; }
          button.dataset.open = "1";
          button.textContent = "▾";
          const holder = h("ul", { class: "vars", "data-parent": String(reference) + item.name });
          row.after(holder);
          await fillVariables(holder, item.variablesReference, depth + 1);
        } }, "▸") : h("span", { class: "twisty" }),
        h("span", { class: "var-name" }, item.name), " = ", h("span", { class: "var-value" }, item.value), item.type ? h("span", { class: "muted" }, `  ${item.type}`) : null);
      list.append(row);
    }
  }

  watchInput.addEventListener("keydown", async (event) => {
    if (event.key !== "Enter" || !watchInput.value.trim() || state !== "stopped") return;
    watchResult.hidden = false;
    try {
      const result = await dap.evaluate(watchInput.value.trim(), selectedFrame ? selectedFrame.id : undefined);
      watchResult.textContent = `${watchInput.value.trim()} = ${result.result}`;
    } catch (error) {
      watchResult.textContent = error.message;
    }
  });

  function paintBreakpoints() {
    clear(breakpointList);
    let any = false;
    for (const [path, lines] of ctx.breakpoints) {
      for (const line of [...lines].sort((a, b) => a - b)) {
        any = true;
        breakpointList.append(h("li", {}, h("button", { class: "link-button", onclick: () => ctx.openFile(path, line, 1) }, `${path}:${line}`),
          h("button", { class: "small", "aria-label": `${t("debug.removeBreakpoint")} ${path}:${line}`, onclick: () => ctx.toggleBreakpoint(path, line) }, "✕")));
      }
    }
    if (!any) breakpointList.append(h("li", { class: "muted" }, t("debug.noBreakpoints")));
  }

  dap.on("stopped", (body) => showStopped(body));
  dap.on("continued", () => { if (state === "stopped") setState("running"); });
  dap.on("output", (body) => { if (body.output && body.category !== "telemetry") log(body.output.replace(/\n$/, ""), body.category === "stderr" ? "error" : ""); });
  dap.on("terminated", () => { log(t("debug.terminated"), "muted"); dap.stop(); });
  dap.on("exited", (body) => log(t("debug.exited", { code: body.exitCode ?? "?" }), "muted"));
  dap.on("ended", cleanup);
  ctx.bus.on("breakpoints-changed", async ({ path }) => {
    paintBreakpoints();
    if (dap.active && (state === "running" || state === "stopped")) await dap.setBreakpoints(absolute(path), [...(ctx.breakpoints.get(path) || [])].sort((a, b) => a - b)).catch(() => {});
  });
  ctx.bus.on("targets-changed", fillTargets);
  ctx.bus.on("panel-shown:debug", () => { fillTargets(); paintBreakpoints(); });
  ctx.debugCommand = (name) => {
    if (name === "start") return start();
    if (name === "stop") return dap.stop();
    if (name === "continue") return step("continue");
    if (name === "over") return step("next");
    if (name === "into") return step("stepIn");
    if (name === "out") return step("stepOut");
    return undefined;
  };
  ctx.debugState = () => state;
  fillTargets();
  paintBreakpoints();
  setState("idle");
}
