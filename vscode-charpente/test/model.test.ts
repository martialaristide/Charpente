import assert from "node:assert/strict";
import { test } from "node:test";
import { pathToUri, uriToPath } from "../src/client";
import { BuildTarget, buildArguments, convertDiagnostics, debugAdapterArgv, errorCodeIn, resolveDebugConfiguration, statusText, targetItems, taskArgv } from "../src/model";

const target = (name: string, run: boolean, deps: string[] = []): BuildTarget => ({
  id: { uri: `file:///p?id=${name}` },
  displayName: name,
  tags: [run ? "application" : "library"],
  languageIds: ["cpp"],
  dependencies: deps.map((d) => ({ uri: `file:///p?id=${d}` })),
  capabilities: { canCompile: true, canTest: false, canRun: run, canDebug: false },
});

test("targets are sorted and marked runnable", () => {
  const items = targetItems([target("b_app", true, ["a_lib"]), target("a_lib", false)]);
  assert.deepEqual(items.map((i) => i.label), ["a_lib", "b_app"]);
  assert.equal(items[0].contextValue, "target");
  assert.equal(items[1].contextValue, "runnable");
  assert.deepEqual(items[1].dependencies, ["a_lib"]);
});

test("build arguments follow the settings", () => {
  assert.deepEqual(buildArguments({ configuration: "Release", platform: "" }), ["--config", "Release"]);
  assert.deepEqual(buildArguments({ configuration: "", platform: " wasm32-wasi " }), ["--config", "Debug", "--platform", "wasm32-wasi"]);
});

test("task command lines never use a shell and honour the definition", () => {
  const s = { configuration: "Debug", platform: "" };
  assert.deepEqual(taskArgv(["charpente"], { command: "build" }, s), ["charpente", "build", "--config", "Debug"]);
  assert.deepEqual(taskArgv(["python", "-m", "charpente"], { command: "build", target: "app", config: "Release" }, s), [
    "python", "-m", "charpente", "build", "--config", "Release", "--target", "app",
  ]);
  assert.deepEqual(taskArgv(["charpente"], { command: "check" }, s), ["charpente", "check"]);
  assert.deepEqual(taskArgv(["charpente"], { command: "test" }, { configuration: "Debug", platform: "linux-x64" }), [
    "charpente", "test", "--config", "Debug", "--platform", "linux-x64",
  ]);
});

test("diagnostics are converted from BSP", () => {
  const out = convertDiagnostics([
    { range: { start: { line: 4, character: 2 } }, severity: 2, message: "unused", code: "W1" },
    { message: "no range" },
    { range: { start: { line: 0, character: 0 } }, severity: 99, message: "odd severity", code: null },
  ]);
  assert.deepEqual(out.map((d) => d.severity), ["warning", "error", "error"]);
  assert.equal(out[0].line, 4);
  assert.equal(out[0].code, "W1");
  assert.equal(out[2].code, undefined);
  assert.equal(out[1].source, "charpente");
});

test("status text", () => {
  assert.match(statusText({ name: "demo", configuration: "Debug" }), /check/);
  assert.match(statusText({ name: "demo", configuration: "Debug", building: true }), /sync/);
  assert.match(statusText({ name: "demo", configuration: "Debug", ok: false }), /error/);
  assert.equal(statusText({ configuration: "Debug", error: "x" }), "$(error) Charpente");
});

test("error codes are found in messages", () => {
  assert.equal(errorCodeIn("charpente: [CH2001] Compiler not found"), "CH2001");
  assert.equal(errorCodeIn("nothing here"), undefined);
});

test("file URIs round-trip, including spaces and Windows drives", () => {
  for (const p of ["C:\\Users\\Ada Lovelace\\my proj", "/home/ada/é ü", "D:/x/y"]) {
    const back = uriToPath(pathToUri(p));
    assert.equal(back, p.replace(/\\/g, "/"));
  }
  assert.throws(() => uriToPath("http://example.com/x"), /not a file/);
});

test("the debug adapter is started as an argument list", () => {
  assert.deepEqual(debugAdapterArgv(["charpente"], "/p"), ["charpente", "debug-adapter", "--root", "/p"]);
  assert.deepEqual(debugAdapterArgv(["python", "-m", "charpente"], "C:\my proj"), ["python", "-m", "charpente", "debug-adapter", "--root", "C:\my proj"]);
});

test("a launch configuration gets its defaults, and a program is left alone", () => {
  assert.deepEqual(resolveDebugConfiguration({}, { configuration: "Release", platform: "" }), {
    type: "charpente", request: "launch", name: "Charpente: debug the program", config: "Release",
  });
  assert.equal(resolveDebugConfiguration({ target: "app", config: "Debug" }, { configuration: "Release", platform: "" }).config, "Debug");
  assert.equal(resolveDebugConfiguration({}, { configuration: "Debug", platform: " wasm32-wasi " }).platform, "wasm32-wasi");
  const direct = resolveDebugConfiguration({ program: "/x/y", name: "mine" }, { configuration: "Release", platform: "linux-x64" });
  assert.deepEqual(direct, { program: "/x/y", name: "mine", type: "charpente", request: "launch" });
});
