// Devices panel: connected Android / HarmonyOS devices, deploy, and live logs (logcat, hilog).
import { clear, h, parseLocation } from "../util.js";

export function mountDevices(ctx, element) {
  const { rpc, t } = ctx;
  const list = h("ul", { class: "devices" });
  const notes = h("ul", { class: "muted device-notes" });
  const log = h("div", { class: "log", role: "log", tabindex: 0 });
  const targetSelect = h("select", { "aria-label": t("devices.target") });
  const platformSelect = h("select", { "aria-label": t("devices.platform") }, ["android-arm64", "android-x86_64", "harmonyos-arm64", "ios-arm64"].map((p) => h("option", { value: p }, p)));
  const output = h("pre", { class: "output small-output", hidden: true });
  clear(element).append(
    h("div", { class: "toolbar" }, h("button", { class: "small", onclick: paint }, "⟳ ", t("devices.refresh")), targetSelect, platformSelect),
    list, notes, output, h("h4", {}, t("devices.logs")), log);

  let stream = null;
  let release = null;

  function fillTargets() {
    clear(targetSelect).append(...ctx.targets.filter((x) => x.capabilities.canRun).map((x) => h("option", { value: x.displayName }, x.displayName)));
  }

  async function deploy(device) {
    if (!targetSelect.value) {
      ctx.toast(t("devices.needTarget"), "error");
      return;
    }
    output.hidden = false;
    output.textContent = t("devices.deploying", { target: targetSelect.value, device: device.id });
    try {
      const result = await rpc.request("charpente/deploy", { target: targetSelect.value, device: device.id, platform: platformSelect.value, config: ctx.config() });
      output.textContent = result.output || (result.ok ? t("devices.deployed") : t("devices.deployFailed"));
    } catch (error) {
      output.textContent = error.message;
    }
  }

  async function logs(device) {
    await stopLogs();
    clear(log);
    try {
      const { id } = await rpc.request("charpente/devices/logs", { id: device.id, platform: device.platform });
      stream = id;
      release = rpc.claimStream(id, onStream);
    } catch (error) {
      log.append(h("div", { class: "line error" }, error.message));
    }
  }

  async function stopLogs() {
    if (stream) {
      const id = stream;
      stream = null;
      await rpc.request("charpente/stream/stop", { id }).catch(() => {});
    }
  }

  function onStream(message) {
    if (message.line !== undefined) {
      const row = h("div", { class: "line" }, message.line);
      const location = parseLocation(message.line);
      if (location) row.title = `${location.file}:${location.line}`;
      log.append(row);
      while (log.childElementCount > 2000) log.firstChild.remove();
      log.scrollTop = log.scrollHeight;
    } else if (message.exit !== undefined) {
      log.append(h("div", { class: "line muted" }, t("devices.logEnded", { code: message.exit })));
      stream = null;
      if (release) release();
    }
  }

  async function paint() {
    fillTargets();
    clear(list);
    clear(notes);
    try {
      const { devices, notes: missing } = await rpc.request("charpente/devices");
      if (!devices.length) list.append(h("li", { class: "muted" }, t("devices.none")));
      for (const device of devices) {
        list.append(h("li", { class: "device" }, h("span", { class: "name" }, `${device.name}`), h("span", { class: "muted" }, ` ${device.platform} · ${device.state}`),
          h("button", { class: "small", onclick: () => deploy(device), disabled: device.state !== "device" }, t("devices.deploy")),
          h("button", { class: "small", onclick: () => logs(device) }, t("devices.showLogs"))));
      }
      for (const note of missing) notes.append(h("li", {}, note));
    } catch (error) {
      list.append(h("li", { class: "muted" }, error.message));
    }
  }

  ctx.bus.on("panel-shown:devices", paint);
  ctx.bus.on("targets-changed", fillTargets);
}
